from tornado.httpclient import HTTPClient
from util.provider import ConfigProvider
from decimal import Decimal
import json
from models.order import Order, OrderCollection
from functools import singledispatch, update_wrapper
from abc import abstractmethod
from typing import Union
from models.customer import Customer

class PromoException(Exception):
    pass


def apply_promotion(orders: Union[Order, OrderCollection], code: str, customer: Customer=None):
    """
    applies a promotion with the given code to the given OrderCollection
    if the promotion isn't valid it throws an exception
    :return:
    """
    promotion = PromotionGateway().fetch_promotion(code, customer)
    promotion.validate_and_apply(orders)
    return promotion


def dispatch(func):
    """#https://stackoverflow.com/questions/24601722/how-can-i-use-functools-singledispatch-with-instance-methods"""
    dispatcher = singledispatch(func)

    def wrapper(*args, **kw):
        return dispatcher.dispatch(args[1].__class__)(*args, **kw)

    wrapper.register = dispatcher.register
    update_wrapper(wrapper, func)
    return wrapper


class Promotion:
    """Our promotion model applies as discount to our orders and lines"""

    promo_ref = None

    @abstractmethod
    def validate(self, order):
        """Validate that our promotion can be applied"""

    @abstractmethod
    def apply(self, order):
        """Apply our promotion to the given order(s) """

    @abstractmethod
    def validate_and_apply(self, order):
        """Validate the promotion and apply it if applicable"""

class NoDiscountPromotion(Promotion):
    """No discount Promotion fits the promotion interface but its only function is to clear data from the orders and lines"""

    message = None

    def validate(self, order):
        """We don't need to validate, this is here to clear data and pass a message only"""
        return False

    @dispatch
    def apply(self, order: Order):
        for line in order.lines:
            line["discount"] = 0.00
        order["promo_ref"] = None


    @apply.register(OrderCollection)
    def apply(self, order_collection: OrderCollection):
        for order in order_collection:
            self.apply(order)

    def validate_and_apply(self, order):
        self.apply(order)


class ValuePromotion(Promotion):

    _dollar_value = None
    _minimum_order_value = None

    @property
    def dollar_value(self):
        return self._dollar_value

    @dollar_value.setter
    def dollar_value(self, value):
        self._dollar_value = Decimal(value)

    @property
    def minimum_order_value(self):
        return self._minimum_order_value

    @minimum_order_value.setter
    def minimum_order_value(self, value):
        self._minimum_order_value = Decimal(value)

    @dispatch
    def validate(self, order: Order):
        if self.minimum_order_value <= order.subtotal:
            return True
        return False

    @validate.register(OrderCollection)
    def _(self, order_collection: OrderCollection):
        for order in order_collection:
            if not self.validate(order):
                return False
        return True


    @dispatch
    def validate_and_apply(self, order: Order):
        if self.validate(order):
            self.apply(order)
        else:
            #todo revisit
            raise PromoException('Promo not valid')

    @validate_and_apply.register(OrderCollection)
    def _(self, orders: OrderCollection):
        elligible_orders = OrderCollection()
        for order in orders:
            if self.validate(order):
                elligible_orders.append(order)
            else:
                order["promo_ref"] = None

        self.apply(elligible_orders)

    @dispatch
    def apply(self, order: Order):
        discount = (self.dollar_value / order.subtotal) if order.subtotal > 0 else 0
        for line in order.lines:
            line["discount"] = line.subtotal * discount
        order["promo_ref"] = self.promo_ref

    @apply.register(OrderCollection)
    def _(self, order_collection: OrderCollection):
        discount_per_order = (self.dollar_value / order_collection.subtotal) if order_collection.subtotal > 0 else 0

        for order in order_collection:
            dollar_value = discount_per_order * order.subtotal
            discount = (dollar_value / order.subtotal) if order.subtotal > 0 else 0
            for line in order.lines:
                line["discount"] = line.subtotal * discount
            order["promo_ref"] = self.promo_ref


class PercentPromotion(Promotion):

    _percent_off = None
    _maximum_value = None

    @property
    def percent_off(self):
        return self._percent_off

    @percent_off.setter
    def percent_off(self, value):
        self._percent_off = Decimal(value)

    @property
    def maximum_value(self):
        return self._maximum_value

    @maximum_value.setter
    def maximum_value(self, value):
        self._maximum_value = Decimal(value)

    @dispatch
    def validate(self, order: Order):
        return True

    @validate.register(OrderCollection)
    def _(self, orderCollection: OrderCollection):
        pass

    @dispatch
    def apply(self, order: Order):
        for line in order.lines:
            line["discount"] = line.subtotal * (self._percent_off / Decimal(100))
        pass

    @apply.register(OrderCollection)
    def _(self, order_collection: OrderCollection):
        for order in order_collection:
            self.apply(order)

    @dispatch
    def validate_and_apply(self, order: Order):
        if self.validate(order):
            self.apply(order)
        else:
            #todo revisit
            raise PromoException('Promo not valid')

    @validate_and_apply.register(OrderCollection)
    def _(self, orders: OrderCollection):
        eligible_orders = OrderCollection()
        for order in orders:
            if self.validate(order):
                eligible_orders.append(order)
            else:
                order["promo_ref"] = None
        self.apply(eligible_orders)


# Not being used yet, validation happens in legacy and the promo is treated as a value promotion
# class ReferralPromotion(ValuePromotion):
#
#     _user_ref = None  #a reference to the user this promotion belongs to
#     _referral_ref = None #the referring user


class PromotionGateway:
    def __init__(self, config: ConfigProvider=ConfigProvider()):
        self.base_url = config.get_value('promos.base_url')
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": config.get_value('promos.token')
        }

    def fetch_promotion(self, promo_code, customer: Customer=None)->Promotion:
        url = '{}/v2/promos/{}'.format(self.base_url, promo_code)

        if customer and customer["thirstie_customer_ref"]:
            url += "?thirstie_customer_ref={}&user_ref={}".format(customer["thirstie_customer_ref"], customer["user_ref"])

        
        client = HTTPClient()
        response = client.fetch(url, headers=self.headers)
        body = json.loads(response.body.decode("utf-8"))

        if not body["valid"]:
            return self.create_no_value_discount(**body)
        if body["type"] == 'P':
            return self.create_percent_promotion(**body)
        elif body["type"] == 'A':
            return self.create_value_promotion(**body)

        raise PromoException

    def create_no_value_discount(self, message, **kwargs):
        p = NoDiscountPromotion()
        p.message = message
        return p

    def create_percent_promotion(self, value, max_value, code, **kwargs):
        p = PercentPromotion()
        p.percent_off = value
        p.maximum_value = max_value
        p.promo_ref = code
        return p

    def create_value_promotion(self, value, minimum, code, **kwargs):
        p = ValuePromotion()
        p.dollar_value = value
        p.minimum_order_value = minimum
        p.promo_ref = code
        return p
