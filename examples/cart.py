"""
Cart mixin for Marketplace REST API
Copyright: Thirstie
Created on October 10, 2017
@author: Thirstie
"""
import time, json, logging
from datetime import datetime

from tornado import gen
from tornado.httpclient import HTTPError, AsyncHTTPClient
from tornado.options import options
from concurrent.futures import ThreadPoolExecutor
from concurrent import futures

from models.cart import Cart
from models.order import Order
from models.message import Message
from models.address import Address
from models.customer import Customer
from models.line_item import LineItem
from util.cart import serialize_payload_order
from util.cart import serialize_orders_and_lines
from util.cart import merge_orders
from util.cart import error_responses
from util.cart import warning_responses
from util.provider import ConfigProvider

cart_steps = {'pending': 'PENDING', 'submitted': 'SUBMITTED', 'resubmitted': "RESUBMITTED"}
# Get the configuration provider
provider = ConfigProvider(app_conf=getattr(options, 'config', None))

logging.basicConfig(format='%(levelname)s - %(asctime)s - %(module)s: %(message)s', level=logging.DEBUG)
logger = logging.getLogger()


class CartMixin(object):
    # helper func to get latest cart
    def get_cart_by_time(self, session_uuid):
        # get carts
        dependencies = {Customer: Cart}
        filters = [(Cart, 'session_ref', '=', session_uuid), (Cart, 'status', '=', 'PENDING')]
        carts = self.object_store.models_matching_filter(Cart, filters, None, dependencies=dependencies)

        # sort carts
        sorted_carts = sorted(carts, key=lambda x: x['date_created'], reverse=True)
        return sorted_carts and sorted_carts[0]

    def read_gift_messages(self, cart):
        """ Read gift messages """
        messages = self.object_store.models_with_ids(Message, [order['gift_message_id'] for order in cart.orders])
        return messages

    @gen.coroutine
    def process_cart(self, cart, payment_method_fingerprint, bt_device_data, *args, **kwargs):
        """ Process Cart and All Logistic Orders """
        aux_data = {}
        self.cart_error = None
        # This will become usable once we link v2 customer id to v0 customer id
        # Reading customer id this way is a temporary hack until we figure out
        # how to link v2 customer id to v0 customer id. Set with case.

        # For now use futures, once celery is set up try it
        # customer_id = cart_tasks.read_customer.apply_async(kwargs=kw).get(timeout=0)
        thirstie_customer_ref = yield self.read_customer_from_store()

        if not thirstie_customer_ref:
            logging.error("Thirstie customer ref is not set")
            self.cart_error = "General error reading customer"
            self.set_status(400)

        try:
            # Serialize orders and their lines
            gift_messages = self.read_gift_messages(cart)
            orders_and_lines = serialize_orders_and_lines(cart, gift_messages, "PENDING")

            # Sort orders out and merge if needed
            orders_and_lines = merge_orders(orders_and_lines)
            kw = {"cart": cart,
                  "customer_id": thirstie_customer_ref,
                  "aux_data": aux_data,
                  "orders_and_lines": orders_and_lines,
                  "payment_method_fingerprint": payment_method_fingerprint,
                  "bt_device_data": bt_device_data}
            yield self.process_legacy_payload(**kw)
        except Exception as e:
            error_message = self.cart_error if self.cart_error else e
            logging.error("General error processing payload - {}".format(error_message))
            self.cart_error = error_message
            self.set_status(400)


    @gen.coroutine
    def legacy_cart(self, **kw):
        """ Create Legacy Cart """
        bt_device_data = kw["bt_device_data"]
        payment_method_fingerprint = kw["payment_method_fingerprint"]
        order = kw["order"]
        cart = kw["cart"]
        customer_id = kw["customer_id"]
        payload = serialize_payload_order(customer_id, cart['cart_key'], 
                                          order, payment_method_fingerprint, 
                                          bt_device_data, None)
        kw_create_cart = {"payload": payload,
                          "order": order,
                          "customer_id": customer_id}
        created_cart = yield self.create_legacy_cart(**kw_create_cart)
        return created_cart

    @gen.coroutine
    def process_legacy_payload(self, *args, **kwargs):
        """ Process the legacy payload, call legacy API and process responses """
        cart = kwargs['cart']
        orders_and_lines = kwargs['orders_and_lines']
        # Get the keyword arguments
        customer_id = kwargs['customer_id']
        payment_method_fingerprint = kwargs['payment_method_fingerprint']
        bt_device_data = kwargs['bt_device_data']
        self.cart_error = None
        code = 200
        # Measure time spent in payload calls
        start = time.time()

        carts_to_submit = []
        created_carts = []
        # Go over all logistic orders and their line items and submit to v0

        # Step 1 - create legacy carts
        with ThreadPoolExecutor(len(orders_and_lines)) as executor:
            jobs = []
            for order in orders_and_lines:
                kw = {"payment_method_fingerprint": payment_method_fingerprint,
                      "bt_device_data": bt_device_data,
                      "customer_id": customer_id,
                      "order": order,
                      "cart": cart}
                jobs.append(executor.submit(self.legacy_cart, **kw))

            for job in futures.as_completed(jobs):
                created_cart = yield job.result()
                created_carts.append(created_cart)


        orders_and_lines = sorted(orders_and_lines, key=lambda k: k['order']['order_key']) 
        created_carts = sorted(created_carts, key=lambda k: k['logistic_order_id'])

        for index, created_cart in enumerate(created_carts):
            errors = created_cart.get('errors', None)
            error = created_cart.get('error', None)
            # If legacy cart was successfully created, use it, if not assert 400
            try:
                assert created_cart['status'] == 200
            except AssertionError as e:
                # If errors returned use them to render error messages
                if errors:
                    for error in errors:
                        logging.error("Cart creation error {} - returned {}".format(created_cart['status'],
                                                                                    error['error_code']))
                        self.cart_error = error['error_code']
                else:
                    if error:
                        try:
                            cart_error = json.loads(error)
                        except TypeError as e:
                            cart_error = error

                        self.cart_error = cart_error["message"]
                        self.set_status(400)
                    else:
                        # TODO: Format this exception handling - the case when there's 400 unrelated to cart
                        self.cart_error = created_cart.get('message', "General cart error")

                self.set_status(400)
                raise e
                return None

            order = orders_and_lines[index]
            cart_id = created_cart.get("cart_id", None)
            logistic_order_id = created_cart.get("logistic_order_id", None)

            if cart_id:
                self.order_update(order["order"]["order_key"], cart_id)

            # if not error and not errors:
            # # Serialize payload for the case of cart being submitted - it alredy exists
            payload = serialize_payload_order(customer_id,
                                              cart['cart_key'],
                                              order,
                                              payment_method_fingerprint,
                                              bt_device_data,
                                              logistic_order_id)

            payload["status"] = cart_steps.get("submitted")

            kw = {
                 "order": order,
                 "customer_id": customer_id,
                 "logistic_order_id": logistic_order_id,
                 "payload": payload,
            }
            carts_to_submit.append(kw)

        # Step 3 - submit carts
        with ThreadPoolExecutor(len(carts_to_submit)) as executor:
            jobs = [executor.submit(self.next_order, **cart) for cart in carts_to_submit]
            for job in futures.as_completed(jobs):
                result = yield job.result()
                new_code = result['status']
                code = new_code if new_code != 200 else code
                if code != 200:
                    self.set_status(code)
                    self.cart_error = result["message"]

        end = time.time()
        res_time = end - start
        logging.info("Time elapsed processing payload {} ".format(str(res_time)))
        self.set_status(code)
        return {}

    def order_exists(self, order):
        """ If an order exists, find and return """
        order_key = order['order']['order_key']
        order = self.object_store.model_with_fields(Order,
                                                    order_key=order_key)
        return order

    def order_update(self, order_key, logistic_order_id):
        """ If an order exists, find and return """
        order = self.object_store.model_with_fields(Order,
                                                    order_key=order_key)
        order.update({"thirstie_logistic_order_ref": logistic_order_id})
        self.object_store.update(order)
        return order

    @gen.coroutine
    def read_user_by_ref(self, user_ref):
        """ Get user by reference """
        auth_token = self.request.headers.get('Authorization')
        auth_header = auth_token and {'Authorization': auth_token}
        response = yield self.client.get('/a/v2/users/{}'.format(user_ref), auth_header)
        return json.loads(response.body.decode('utf-8'))

    @gen.coroutine
    def read_customer_from_store(self):
        """ Read the cart and orders by uuid """
        user_ref = self.current_session.get('user', {}).get('ref')
        customer = self.object_store.model_with_fields(Customer, user_ref=user_ref)

        if user_ref:
            if customer and customer['thirstie_customer_ref']:
                return customer['thirstie_customer_ref']
            else:
                return None
        return None

    @gen.coroutine
    def read_cart_from_store(self, key):
        """ Read the cart and orders by key """
        cart = self.object_store.model_with_fields(Cart, cart_key=key)

        auth_token = self.request.headers.get('Authorization')
        auth_header = auth_token and {'Authorization': auth_token}
        self.object_store.model_referenced_by_model(Customer, cart, set_attr='customer')
        self.object_store.models_referencing_model(Order, cart, None, set_attr='orders')

        for order in cart.orders:
            self.object_store.models_referencing_model(LineItem, order, None, set_attr='lines')
            order.delivery_address = self.object_store.model_with_id(Address, order['delivery_address_id'])
            order.delivery_address.delivery_instructions = self.object_store.model_with_id(Message,
                                                                                           order.delivery_address['delivery_message_id'])
            response = yield self.client.get('/c/v2/merchants/{}'.format(order['merchant_ref']), auth_header)
            order.merchant = json.loads(response.body.decode('utf-8'))
        return cart

    @gen.coroutine
    def process_api_request(self, method, url, headers, body):
        """ Legacy API call, mock it when you're testing """
        client = AsyncHTTPClient()
        response = yield client.fetch(url, method=method, headers=headers, body=body)
        client.close()
        return response

    @gen.coroutine
    def create_legacy_cart(self, *args, **kwargs):
        """ Client used to create legacy cart """
        customer_id = kwargs['customer_id']
        payload = kwargs.get('payload', {})
        token = provider.get_value('jwt.token_basic')
        order = kwargs['order']

        headers = {
            "Content-Type": "application/json",
            "Authorization": token
        }
       
        base = provider.get_value('service.thirstie_legacy.base_url')
        version = 'v0'
        cart_url = '{}/{}/payments/user/{}/carts/'.format(base, version, customer_id)

        try:
            body = json.dumps(payload).encode('utf-8')
            response = yield self.process_api_request("POST", cart_url, headers, body)
            result = json.loads(response.body.decode('utf-8'))
            result['message'] = "Payload sent {}".format(body.decode('utf-8'))
            time_now = datetime.strftime(datetime.now(), '%Y-%m-%dT%H:%M:%S')
            logging.info("The cart {} has been created at {} - {} with {}".format(result['cart_id'], 
                                                                                  time_now, 
                                                                                  200, 
                                                                                  result['status']))
        except HTTPError as e:
            cart_error = json.loads(e.response.body.decode('utf-8'))
            cart_errors = cart_error.get("errors", None)
            result = {}
            result['logistic_order_id'] = payload['ext_logistic_order_id']
            if not cart_errors:
                result['status'] = e.code
                result['error'] = e.response.body.decode('utf-8')
                return result

            if e.response and e.response.body:
                logging.error("HTTP error {} on submitting cart - {}".format(e, e.response.body))
                cart_error = json.loads(e.response.body.decode('utf-8'))

                errors = order['order']['order_obj'].errors

                for error in cart_errors:
                    error_response = error_responses.get(error["error_code"], {})

                    key = list(error_response.keys())[0]

                    if any(key in e for e in errors):
                        error_index = next((index for (index, d) in enumerate(errors) if d[key]), None)
                        errors[error_index].get(key).append(error_response.get(key)[0])
                        errors[error_index][key] = list(set(errors[error_index][key]))
                    else:
                        errors.append(error_response)
            else:
                error_response = error_responses.get("CART_ERROR")
                order['order']['order_obj'].errors.append(error_response)

            http_error = "HTTP Error {} creating a new cart - {}"
            logging.error(http_error.format(e.code, e.response.body.decode('utf-8')))
            result['status'] = e.code
            result['error'] = e.response.body.decode('utf-8')
            return result
        except Exception as e:
            logging.error("General error on creating a new cart {} - {}".format(500, e))
            result = {}
            result['logistic_order_id'] = payload['ext_logistic_order_id']
            result['status'] = 500
            result['error'] = {"message": "General error on creating a new cart - {}".format(e)}
            order['order']['order_obj'].errors.append("CART_ERROR")
            return result
        return {'status': 200, 'message': result, 'cart_id': result.get('cart_id', ""),
                'logistic_order_id': result.get('logistic_order_id', "")}

    @gen.coroutine
    def next_order(self, **kw):
        order = kw['order']
        payload = kw['payload']
        token = provider.get_value('jwt.token_basic')
        base = provider.get_value('service.thirstie_legacy.base_url')
        version = 'v0'
        headers = {
            "Content-Type": "application/json",
            "Authorization": token,
        }

        try:
            body = json.dumps(payload).encode('utf-8')
            cart_url = "{}/{}/payments/user/{}/carts/{}".format(base,
                                                                version,
                                                                payload['ext_customer_id'],
                                                                payload['ext_logistic_order_id'])
            response = yield self.process_api_request('PUT', cart_url, headers, body)
            result = self.parseJSON(response.body)
            code = 200
            if not result["payment_method"]['name_on_card']:
                payment_method_error = "Invalid payment method provided - logistic order {}"
                logging.error(payment_method_error.format(payload['ext_logistic_order_id']))
                self.set_status(400)
                self.cart_error = "Invalid payment method provided"
                code = 400
            if 'warnings' in result:
                for warning in result["warnings"]:
                    warning_response = warning_responses[warning]
                    order['order']['order_obj'].errors.append(warning_response)
            time_now = datetime.strftime(datetime.now(), '%Y-%m-%dT%H:%M:%S')
            fmt = "The cart {} has been submitted at {} - {} with {}"
            logging.info(fmt.format(result['cart_id'], time_now, 200, result['status']))
        except HTTPError as e:
            result = None
            if e.response and e.response.body:
                cart_error = self.parseJSON(e.response.body) or None

                if not cart_error:
                    logging.error("General {} error on submitting cart {}".format(e.code, e))
                    return {'status': e.code, 'message': e}

                if cart_error['errors']:
                    error_message = ""
                    for i, error in enumerate(cart_error['errors']):
                        if i != 0: 
                            error_message = error_message + ", "
                        error_message = error_message + error['message']
                    result = "HTTP error {} on submitting cart - {}".format(e.code, error_message)
                else:
                    result = "HTTP error {} on submitting cart - {}".format(e.code, cart_error)

                logging.error("HTTP error {} on submitting cart - {}".format(e.code, cart_error))
                errors = order['order']['order_obj'].errors
                # Go over errors returned in response and render their responses
                cart_error_list = cart_error.get("errors", {})
           
                for error in cart_error_list:
                    error_response = error_responses.get(error["error_code"], {})
                    key = list(error_response.keys())[0]

                    if any(key in e for e in errors):
                        error_index = next((index for (index, d) in enumerate(errors) if d[key]), None)
                        errors[error_index].get(key).append(error_response.get(key)[0])
                        errors[error_index][key] = list(set(errors[error_index][key]))
                    else:
                        errors.append(error_response)
            else:
                result = "HTTP error {} on submitting cart - {}".format(e.code, e)
                error_response = error_responses.get("CART_ERROR")
                order['order']['order_obj'].errors.append(error_response)
            code = e.code
        except Exception as e:
            result = "General {} error on submitting cart - {}".format(500, e)
            logging.error("General {} error on submitting cart - {}".format(500, e))
            code = 500

        return {'status': code, 'message': result}
