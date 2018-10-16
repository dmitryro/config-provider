'''
Authentication utility functions
'''

import jwt
import json
import logging
import functools
from uuid import uuid4
from base64 import urlsafe_b64decode as b64decode

from util.data import Data, Base58
from controllers.authorization import AuthEngine
from core.handlers import HTMLRequestHandler


def extract_header(token):
    '''
    Returns the decoded header from a JWT token

    params:
        token: the JWT token string

    returns:
        the token header as a dictionary or None if the header
        could not be decoded
    '''
    enc_header = token.split('.')[0]

    try:
        json_bytes = b64decode(enc_header + '=' * (len(enc_header) % 4))
        return json.loads(json_bytes.decode('ascii'))
    except Exception:
        return None


def uuid_str():
    '''
    Return a [Base58 encoded][1] UUID that can be used to opaquely identify
    applications, sessions, and users to external clients

    [1]: https://en.wikipedia.org/wiki/Base58
    '''
    return Data(uuid4().bytes).stringWithEncoding(Base58)


class JWTAuthenticated(object):
    '''
    Provides a `current_session` property for the request handler class and a
    `get_current_session` method to retrieve the session (and associated
    application and possibly user) from either a token cookie or Bearer JWT
    '''

    @property
    def current_session(self):
        '''
        Trigger the `get_current_session` method if no session has been
        populated, and cache the result.
        '''
        if not hasattr(self, '_current_session'):
            self._current_session = self.get_current_session()
        return self._current_session

    @current_session.setter
    def current_session(self, value):
        '''
        Set a new value for `current_session`
        '''
        self._current_session = value

    def _get_public_key(self, uuid):
        '''
        Return a key pair model retrieved by looking up the uuid in the
        object store or None if no key pair was found

        params:
            uuid: the key pair uuid as a string

        returns:
            the key pair with the specified string
        '''
        key = None
        key_hash = 'key_pair:{0}'.format(uuid)
        key_lookup = self.kv_store.get_value(key_hash)

        if key_lookup:
            _, id = key_lookup.split(':')
            key = self.kv_store.get_object(key, id)

        if not key:
            key = self.object_store.model_with_fields(key, uuid=uuid)

        if not key:
            return None

        self.kv_store.set_value(key_hash, self.kv_store.build_key(key))
        return key

    def get_current_session(self):
        '''
        Return a session model object retrieved by looking up the key
        from the supplied bearer token.

        If the session has a user associated with it, this method will also
        set the `current_user` property on the request handler instance.
        '''
        header = self.request.headers.get('Authorization', '')
        token_str = header.startswith('Bearer ') and header.split(' ', 2)[-1]

        if not token_str:
            # We actually couldn't find a token.
            logging.warn('could not find a token in headers')
            return None

        header = extract_header(token_str)

        if not header:
            # The token did not contain a decodable header
            logging.error('could not decode a token in the string "%s"', token_str)
            return None

        alg = header.get('alg', None)
        key_id = header.get('kid', None)

        if alg == 'RS256':
            if not key_id:
                # The header did not have a `kid` field,
                # so we can't look up the public key
                logging.error('couldnt find a key ID in the token "%s"', token_str)
                return None
            #  self._get_public_key(key_id)
            key = None

            # if not key:
            #     logging.error('no key associated with key id %s', key_id)
            #     return None

            try:
                token = jwt.decode(token_str, 
                                   key and key.public_key(),
                                   algorithms=['RS256'], 
                                   verify=False)   
            except Exception as e:
                logging.error('unable to verify token: %s', e)
                return None

            session_dict = {
                'session': token['sub'],
            }

            if 'com.thirstie:usr' in token:
                session_dict['user'] = {
                    'ref': token['com.thirstie:usr'],
                    'roles': token['com.thirstie:usr.roles']
                }

            if 'com.thirstie:app' in token:
                session_dict['application'] = {
                    'ref': token['com.thirstie:app'],
                    'roles': token['com.thirstie:app.roles']
                }

            return session_dict
        else:
            logging.error('unexpected algorithm "%s"', alg)
            return None

    @staticmethod
    def authenticated(method):
        '''
        Returns a wrapper function that executes the decorated method if
        a user is logged in, and clears the session and returns a 401 status
        if no user was found.
        '''
        @functools.wraps(method)
        def wrapper(self, *args, **kwargs):
            '''
            Conditionally calls `method` if the `self.current_user`
            property is set.
            '''
            if not self.current_session:
                # TODO: Figure out what to do here, since we don't know how
                # the session was communicated (does nginx clear the cookie
                # for us?)
                if isinstance(self, HTMLRequestHandler):
                    self.set_status(302)
                    redirect = '?redirect={url}'.format(url=self.request.path)
                    loc_fmt = '{scheme}://{host}/login{query_str}'
                    location = loc_fmt.format(
                            scheme=self.request.protocol,
                            host=self.request.host,
                            query_str=redirect
                        )
                    self.set_header('Location', location)
                else:
                    self.set_status(401)
                return
            return method(self, *args, **kwargs)
        return wrapper

    @property
    def authority(self):
        if not hasattr(self, '_authority'):
            self._authority = AuthEngine(self.current_session)
        return self._authority
