"""
Utility functions for working with cart serializations
"""

import json, logging, uuid, decimal
from datetime import datetime

from tornado import gen
from tornado.httpclient import AsyncHTTPClient, HTTPClient, HTTPError
from tornado.options import options

from util.provider import ConfigProvider

# Get the configuration provider
provider = ConfigProvider(app_conf=getattr(options, 'config', None))
# Round dollars and cents up when period used
D = decimal.Decimal
cent = D('0.01')
shipping_methods = {'shipping': 'SHIPPING',
                    'on_demand': 'PHYSICAL',
                    'scheduled': 'PHYSICAL'}

error_responses = {"CART_INVALID_PROMOCODE": {"promo_code": ["This promo code is already used."]},
                   "CART_INVALID_BILLING": {"cart": ["Invalid cart billing"]},
                   "CART_INVALID_STORE": {"cart": ["Invalid cart store"]},
                   "CART_INVALID_ITEMS": {"cart": ["Cart has invalid items"]},
                   "CART_INVALID_USER": {"cart": ["Invalid cart user"]},
                   "CART_DELIVERY_FEE_INVALID": {"cart": ["Cart delivery fee is invalid"]},
                   "CART_ERROR": {"cart": ["Cart has an error."]},
                   "CART_MINIMUM_DELIVERY": {"merchant": ["Minimum delivery is not satisfied."]},
                   "CART_MISSING_REQUIRED_FIELD": {"cart": ["Cart missing requred field"]},
                   "CART_PAYMENT_METHOD_FAILED": {"cart": ["Payment method failed."]},
                   "CART_PAYMENT_INTEGRATION_REQUIRED": {"cart": ["Merchant requires payment integration"]},
                   "CART_PAYMENT_INTEGRATION_TRANSACTION_FAILED": {"cart": ["Cart integration failed."]},
                   "CART_PAYMENT_INTEGRATION_TRANSACTION_NOTAUTHORIZED": {"cart": ["Cart transaction is not authorized"]},
                   "CART_STORE_CLOSED": {"merchant": ["Store is closed."]},
                   "CART_MININUM_DELIVERY": {"cart": ["Minimum delivery not met"]},
                   "UNKNOWN_ERROR": {"cart": ["Unknown error"]}}

warning_responses = {"CART_MININUM_DELIVERY": {"cart": ["Minimum delivery not met"]}}

order_statuses = {"SUBMITTED": {"status": "SUBMITTED"},
                  "PENDING": {"status": "PENDING"},
                  "ACCEPTED": {"status": "ACCEPTED"},
                  "REJECTED": {"status": "REJECTED"},
                  "RESUBMITTED": {"status": "RESUBMITTED"},
                  "REJECTED_MERCHANT":  {"status": "REJECTED_MERCHANT"},
                  "REJECTED_PAYMENT": {"status": "REJECTED_PAYMENT"},
                  "COMPLETED": {"status": "COMPLETED"}}


def process_cents(amount):
    """ Add a trailing zero when needed """
    amount = str(amount)
    digits = amount[::-1].find('.')
    # In case we have 1 digit amount - add 0
    if digits == 1:
        amount = amount + '0'
    return amount


def quantize(amount, option):
    """ Round any periodic 9s to the actual amount """
    rounding = {"tax": decimal.ROUND_HALF_EVEN, "tip": decimal.ROUND_HALF_EVEN, "discount": decimal.ROUND_HALF_EVEN}
    return str(D(amount).quantize(cent, rounding=rounding[option]))


@gen.coroutine
def process_orders(orders):
    """ Use this function to resort orders by logistic orders """
    pass


def generate_uuid():
    return uuid.uuid4().hex


def split_by_delivery(orders_and_lines):
    return orders_and_lines


def sort_by_merchant(orders):
    orders = sorted(orders, key=lambda o: o['merchant']['id'])
    return orders


def merchant_id(order):
    try:
        return order['merchant']['id']
    except Exception as e:
        return -1


def item_exists(lines, line):
    for i, ln in enumerate(lines):
        if int(ln['offering_ref']) == int(line['offering_ref']):
            return i
    return -1


def merge_two_orders(order_one, order_two):
    """ Merge two orders belonging to the same tmk - update quantities """
    for indx, line in enumerate(order_two['lines']):
        lines = order_one['lines']
        item_index = item_exists(lines, line)

        # Item was located - increase quantity
        if item_index >= 0:

            qty = int(line['quantity']) + int(order_one['lines'][item_index]['quantity'])
            order_one['lines'][item_index]['quantity'] = qty
        else:
            # No item - just add to list
            order_one['lines'].append(line)

    return order_one


def current(current_id, next_id):
    """ Check if current id is legit, same for next """
    return (current_id != -1 and next_id != -1)


def next_order(*args, **kw):
    """ Stand-alone version of cart mixin method doing the API call """
    customer_id = kw['customer_id']
    logistic_order_id = kw['logistic_order_id']
    payload = kw['payload']
    base = provider.get_value('service.thirstie_legacy.base_url')
    version = 'v0'
    token = provider.get_value('jwt.token_basic')
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    client = HTTPClient()

    try:
        body = json.dumps(payload).encode('utf-8')
        cart_url = "{}/{}/payments/user/{}/carts/{}".format(base,
                                                            version,
                                                            customer_id,
                                                            logistic_order_id)

        response = client.fetch(cart_url, method='POST', headers=headers, body=body)
        result = json.loads(response.body.decode('utf-8'))
        result['status'] = 202
    except HTTPError as e:
        cart_error = json.loads(e)
        result = json.loads(e.decode('utf-8'))
        result['error'] = cart_error
        result['status'] = e.code
    except Exception as e:
        response = {}
        response['error'] = "General error intercepted - {} ".format(e)
        response['status'] = 500
        result = response
        result['status'] = 500

    client.close()
    return result


def merge_orders(orders_and_lines):
    """ Method to check for orders in the right arrangement """
    orders_and_lines = split_by_delivery(orders_and_lines)

    # Sort orders by merchant id - then compare one by one
    orders_and_lines = sort_by_merchant(orders_and_lines)

    # Strore here the orders that were merged and need to be deleted
    clear_redundant = {}

    for i, order in enumerate(orders_and_lines):

        if i < len(orders_and_lines) - 1:
            # Get current id and next id
            current_id = merchant_id(orders_and_lines[i])
            next_id = merchant_id(orders_and_lines[i+1])

            if current(current_id, next_id):

                if not clear_redundant:
                    clear_redundant[current_id] = []
                    initial = i

                if not clear_redundant.get(current_id):
                    clear_redundant[current_id] = []
                    initial = i

                if current_id == next_id:
                    clear_redundant[current_id].append(i+1)

                    merged_order = merge_two_orders(orders_and_lines[initial],
                                                    orders_and_lines[i+1])
                    orders_and_lines[i] = merged_order
                else:
                    for indx in clear_redundant[current_id]:
                        orders_and_lines.pop(indx)
    return orders_and_lines


def serialize_orders_and_lines(cart, gift_messages, cart_status):
    orders_and_lines = []

    for order in cart.orders:
        gift_message = None
        is_gift = False

        for gift in gift_messages:
            if gift.id == order['gift_message_id']:
                gift_message = gift

        delivery_date = order.get('delivery_date', None)

        if gift_message:
            is_gift = True
            order.gift_message = gift_message

        _order = {}
        _order['order_obj'] = order
        _order['id'] = order['id']
        _order['external_reference'] = order['external_reference'] or ""
        _order['merchant_ref'] = order['merchant_ref']
        _order['cart_id'] = cart['id']
        _order['lines'] = order.lines
        _order['tax'] = float(order.tax)
        _order['promo_ref'] = order['promo_ref']
        _order['v2_discount_amt'] = order.discount
        _order['v2_discount_total'] = cart.discount
        _order['order_key'] = order['order_key']
        _order['tip_amount'] = str(order.tip)

        if delivery_date:
            delivery_begin_time = "{}T{}".format(delivery_date, str(order['delivery_start_time']))
            delivery_end_time = "{}T{}".format(delivery_date, str(order['delivery_end_time']))
            start_time = datetime.strptime(delivery_begin_time, '%Y-%m-%dT%H:%M:%S')
            end_time = datetime.strptime(delivery_end_time, '%Y-%m-%dT%H:%M:%S')
            _order['delivery_scheduled_begin'] = start_time
            _order['delivery_scheduled_end'] = end_time

        address = {'street_1': order.delivery_address['street_1'],
                   'street_2': order.delivery_address['street_2'],
                   'street_3': order.delivery_address['street_3'],
                   'first_name': order.delivery_address['first_name'],
                   'last_name': order.delivery_address['last_name'],
                   'company': order.delivery_address['company'],
                   'email': order.delivery_address['email'],
                   'telephone': order.delivery_address['telephone'],
                   'city': order.delivery_address['municipality'],
                   'zip_code': order.delivery_address['post_code'],
                   'state': order.delivery_address['administrative_region']}

        recipient_first = order.delivery_address['first_name'] or ""
        recipient_last = order.delivery_address['last_name'] or ""
        recipient_name = "{} {}".format(recipient_first, recipient_last)
        instructions = order.delivery_address.delivery_instructions
        orders_and_lines.append({"order": _order,
                                 "status": cart_status,
                                 "delivery_type": shipping_methods[order['delivery_method']],
                                 "merchant_id": order.merchant.get('tmk'),
                                 "merchant": {"id": order.merchant.get('tmk')},
                                 "delivery_instructions": (instructions and instructions['message']) or "", 
                                 "delivery_address": address,
                                 "recipient_name": recipient_name,
                                 "gift_info": {"gift_wrap": is_gift,
                                               "gift_message": gift_message["message"] if gift_message else ""},
                                 "lines": order.lines})
    return orders_and_lines


def create_legacy_crt(*args, **kwargs):
    """ This is used with celery, but same as create_legacy_cart """
    customer_id = kwargs['customer_id']
    payload = kwargs.get('payload', {})
    token = provider.get_value('jwt.token_basic')

    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }

    client = HTTPClient()
    base = provider.get_value('service.thirstie_legacy.base_url')
    version = 'v0'

    cart_url = '{}/{}/payments/user/{}/carts/'.format(base, version, customer_id)

    try:
        body = json.dumps(payload).encode('utf-8')
        response = client.fetch(cart_url, method='POST', headers=headers, body=body)
        result = json.loads(response.body.decode('utf-8'))
        result['message'] = "Payload sent {}".format(body.decode('utf-8'))
        time_now = datetime.strftime(datetime.now(), '%Y-%m-%dT%H:%M:%S')
        logging.info("The cart {} has been created at {} - {} with {}".format(result['cart_id'], 
                                                                              time_now, 
                                                                              200, 
                                                                              result['status']))
    except HTTPError as e:
        result = {}
        result['error'] = "HTTPError {} intercepted - {} ".format(e.code, e)
        result['status'] = e.code
        result['message'] = "Payload sent {}".format(body.decode('utf-8'))
        client.close()
        return result
    except Exception as e:
        result = {}
        result['error'] = {"message": "General error creating a new cart - {}".format(e)}
        result['status'] = 500
        result['message'] = "Payload sent {}".format(body.decode('utf-8'))
        client.close()
        return result

    client.close()

    return {'status': 200,
            'message': result,
            'logistic_order_id': result.get('logistic_order_id', ""),
            'cart_id': result.get('cart_id', "")}


def read_braintree_token(*args, **kwargs):
    """ Read Braintree Token """
    th_customer_id = kwargs['th_customer_id']
    base = provider.get_value('service.thirstie_legacy.base_url')
    version = 'v0'
    token_url = '{}/{}/payments/token/braintree/{}'.format(base, version, th_customer_id)

    client = HTTPClient()
    response = None
    token = provider.get_value('jwt.token')

    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
        "Access-Control-Allow-Origin": "*",
        "Authorization": token
    }

    try:
        response = client.fetch(token_url, method='GET', headers=headers)
        result = json.loads(response.body.decode('utf-8'))
    except HTTPError as e:
        logging.error("HTTPError intercepted - {} ".format(e))
        response = {}
        response['error'] = "HTTPError intercepted - {} ".format(e)
        response['status'] = e.code
        result = response
    except Exception as e:
        logging.error("Exception intercepted - {} ".format(e))
        response = {}
        response['error'] = "General error intercepted - {} ".format(e)
        response['status'] = 500
        result = response
    client.close()
    return result


@gen.coroutine
def read_bearer_token(*args, **kwargs):
    customer_id = kwargs['customer_id']

    client = HTTPClient()
    response = None
    token = provider.get_value('jwt.token_basic')
    base = provider.get_value('service.thirstie_legacy.base_url')
    version = 'v0'
    token_url = '{}/{}/payments/user/{}'.format(base, version, customer_id)
    # Read the token from configuration
    token = provider.get_value('jwt.token_basic')

    # Set the headers to communicate
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }

    try:
        response = client.fetch(token_url, method='GET', headers=headers)
        result = json.loads(response.body.decode('utf-8'))
    except HTTPError as e:
        cart_error = json.loads(e.response.body)
        response = {}
        response['error'] = cart_error
        response['status'] = e.code
        return response
    except Exception as e:
        response = {}
        response['error'] = "General error intercepted - {} ".format(e)
        response['status'] = 500
        return response
    client.close()

    return "Bearer "+result['token']


def extract_item(order):
    """ Merge as an item within logistic order """
    item = {}
    item['name'] = order['product']['name']
    item['tpk'] = order['product']['tpk']
    item['description'] = ''
    item['quantity'] = order['quantity']
    item['price'] = order['price']
    return item


def logistic_order_exists(orders, tmk):
    """ Verify logistic order exists """
    for index, order in enumerate(orders):
        if order['merchant']['tmk'] == tmk:
            return order, index
    return None, -1


def read_transaction_info(order):
    """ Read transaction info for logistic order """
    transaction_info = {
        "total": order["total"],
        "code": order["promo_code"],
        "tax": order["tax_amount"],
        "shipping": order["delivery_fee"],
        "subtotal": order["subtotal"],
        "discount": order["promo_discount"],
    }
    return transaction_info


def merge_item(logistic_order, item):
    """ If an item is within the order, update, add otherwise """
    found = False
    for index, itm in enumerate(logistic_order['items']):
        if itm['tpk'] == item['tpk']:

            try:
                qty = int(itm['quantity']) + int(item['quantity'])
            except Exception:
                qty = itm['quantity']

            itm['quantity'] = qty
            found = True

    if not found:
        logistic_order['items'].append(item)

    return logistic_order


@gen.coroutine
def read_legacy_cart(th_customer_id, logistic_order_id):
    client = HTTPClient()
    base = provider.get_value('service.thirstie_legacy.base_url')
    version = 'v0'
    cart_url = '{}/{}/payments/user/{}/carts/{}'.format(base, version, th_customer_id, logistic_order_id)

    # Read the token from configuration
    token = provider.get_value('jwt.token_basic')

    # Set the headers to communicate
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    try:
        response = client.fetch(cart_url, method='GET', headers=headers)
        result = json.loads(response.body.decode('utf-8'))
    except HTTPError as e:
        payment_user_error = json.loads(e.response.body)
        response = {}
        response['error'] = payment_user_error
        response['status'] = e.code
        return response
    except Exception as e:
        response = {}
        response['error'] = "General error intercepted - {} ".format(e)
        response['status'] = 500
        return response
    client.close()
    return result


@gen.coroutine
def read_token(customer_id):
    """ Call the legacy API to get Payment User """
    client = AsyncHTTPClient()
    response = None

    token = provider.get_value('jwt.token')
    base = provider.get_value('service.thirstie_legacy.base_url')
    version = 'v0'
    payment_user_url = '{}/{}/payments/user/{}'.format(base, version, customer_id)
    # Read the token from configuration
    token = provider.get_value('jwt.token_basic')

    # Set the headers to communicate
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }

    try:
        response = yield client.fetch(payment_user_url, method='GET', headers=headers)
        result = json.loads(response.body.decode('utf-8'))
    except HTTPError as e:
        cart_error = json.loads(e.response.body)
        response = {}
        response['error'] = cart_error
        response['status'] = e.code
        return response
    except Exception as e:
        response = {}
        response['error'] = "General error intercepted - {} ".format(e)
        response['status'] = 500
        return response
    client.close()

    return result['token']


def serialize_payload_order(th_customer_id, ext_commercial_order_id, 
                            order, payment_method_fingerprint,
                            bt_device_data, ext_logistic_order_id):
    """ Serialize order payload """
    gift_info = order.get('gift_info', {})
    is_gift = gift_info.get("gift_wrap", False)

    address = order['delivery_address']
    status = order['status']
    delivery_type = order['delivery_type']

    try:
        fmt = "%Y-%m-%dT%H:%M:%S"
        delivery_scheduled_begin = order['order']['delivery_scheduled_begin'].strftime(fmt)
        delivery_scheduled_end = order['order']['delivery_scheduled_end'].strftime(fmt)
    except KeyError:
        delivery_scheduled_begin = None
        delivery_scheduled_end = None

    payload = {
        "status": status,
        "delivery_type": delivery_type,
        "tmk": order['merchant']['id'],
        "ext_customer_id": th_customer_id,
        "ext_shipping_fee": 0.0,
        "ext_tax_amount": quantize(order['order']['tax'], "tax"),
        "ext_commercial_order_id": ext_commercial_order_id,
        "delivery_scheduled_begin": delivery_scheduled_begin,
        "delivery_scheduled_end": delivery_scheduled_end,
        "device_data": bt_device_data,
        "payment_method_fingerprint": payment_method_fingerprint,
        "recipient": {
            "recipient_name": "{} {}".format(address['first_name'], address['last_name']),
            "gift_flag": is_gift,
            "gift_note": gift_info.get('gift_message', None) if is_gift else None,
            "address": {
                "city": address['city'],
                "address1": address['street_1'],
                "address2": address['street_2'] or '',
                "state": address['state'],
                "zip_code": address['zip_code']
            }
        },
        "tip_amount": quantize(order['order'].get('tip_amount', 0), "tip"),
        "promo_code": order['order'].get('promo_ref', None),
        "v2_discount_amt": quantize(order['order'].get('v2_discount_amt', 0), "discount"),
        "v2_discount_total": quantize(order['order'].get('v2_discount_total', 0), "discount"),
        "orders": [{"offering_id": line['offering_ref'], 
                    "quantity": line['quantity']} for line in order['lines']],
                    "instructions": order['delivery_instructions'] or '',
    }

    if ext_logistic_order_id:
        payload["ext_logistic_order_id"] = ext_logistic_order_id
    else:
        payload["ext_logistic_order_id"] = order['order']['order_key']
    return payload
    
