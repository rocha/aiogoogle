__all__ = [
    'Aiogoogle'
]


import json
from pprint import pprint
from urllib.parse import urlencode

from .utils import _dict
from .models import Request
from .resource import GoogleAPI
from .auth.managers import Oauth2Manager, ApiKeyManager, OpenIdConnectManager
from .sessions.aiohttp_session import AiohttpSession
from .data import DISCOVERY_SERVICE_V1_DISCOVERY_DOC


# Discovery doc reference https://developers.google.com/discovery/v1/reference/apis

class Aiogoogle:
    '''
    Arguments:

        session_factory (aiogoogle.sessions.abc.AbstractSession): AbstractSession Implementation. Defaults to ``aiogoogle.sessions.aiohttp_session.AiohttpSession``

        api_key (aiogoogle.auth.creds.ApiKey): Google API key
        
        user_creds (aiogoogle.auth.creds.UserCreds): OAuth2 User Credentials 

        client_creds (aiogoogle.auth.creds.ClientCreds): OAuth2 Client Credentials
        
        timeout (int): Timeout for this class's async context manager
            
    Note: 
    
        In case you want to instantiate a custom session with initial parameters, you can pass an anonymous factory. e.g. ::
        
            >>> sess = lambda: Session(your_custome_arg, your_custom_kwarg=True)
            >>> aiogoogle = Aiogoogle(session_factory=sess)
    '''

    def __init__(self, session_factory=AiohttpSession, api_key=None, user_creds=None, client_creds=None, timeout=None):

        self.session_factory = session_factory
        self.timeout = timeout
        self.active_session = None

        # Keys
        self.api_key = api_key
        self.user_creds = user_creds
        self.client_creds = client_creds

        # Auth managers
        self.api_key_manager = ApiKeyManager()
        self.oauth2 = Oauth2Manager(self.session_factory)
        self.openid_connect = OpenIdConnectManager(self.session_factory)

        # Discovery service
        self.discovery_service = GoogleAPI(DISCOVERY_SERVICE_V1_DISCOVERY_DOC)

    #-------- Discovery Service's only 2 methods ---------#

    async def list_api(self, name, preffered=None, fields=None):
        '''
        https://developers.google.com/discovery/v1/reference/apis/list

        The discovery.apis.list method returns the list all APIs supported by the Google APIs Discovery Service.
        
        The data for each entry is a subset of the Discovery Document for that API, and the list provides a directory of supported APIs.
        
        If a specific API has multiple versions, each of the versions has its own entry in the list.

        Example:

            ::

                >>> await aiogoogle.list_api('youtube')

                {
                    "kind": "discovery#directoryList",
                    "discoveryVersion": "v1",
                    "items": [
                        {
                            "kind": "discovery#directoryItem",
                            "id": "youtube:v3",
                            "name": "youtube",
                            "version": "v3",
                            "title": "YouTube Data API",
                            "description": "Supports core YouTube features, such as uploading videos, creating and managing playlists, searching for content, and much more.",
                            "discoveryRestUrl": "https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest",
                            "discoveryLink": "./apis/youtube/v3/rest",
                            "icons": {
                                "x16": "https://www.google.com/images/icons/product/youtube-16.png",
                                "x32": "https://www.google.com/images/icons/product/youtube-32.png"
                            },
                            "documentationLink": "https://developers.google.com/youtube/v3",
                            "preferred": true
                        }
                    ]
                }

        Arguments:

            name (str): Only include APIs with the given name.

            preffered (bool): Return only the preferred version of an API.  "false" by default.

            fields (str): Selector specifying which fields to include in a partial response.

        Returns:

            dict:

        Raises:

            aiogoogle.excs.HTTPError
        '''
        
        request = self.discovery_service.apis.list(name=name, preffered=preffered, fields=fields, validate=False)
        if self.active_session is None:
            async with self:
                res = await self.as_anon(request)
        else:
            res = await self.as_anon(request)
        return res

    async def discover(self, api_name, api_version=None, validate=True):
        ''' 
        Donwloads a discovery document from Google's Discovery Service V1 and sets it a ``aiogoogle.resource.GoogleAPI``

        Note:

            It is recommended that you explicitly specify an API version.
            
            When you leave the API version to None, Aiogoogle uses the ``list_api`` method to search for the best fit version of the given API name.
            
            The problem is that Google's discovery service sometimes does not return the latest version of a given API. Rather, returns the "preffered" one.
        
        Arguments:

            api_name (str): API name to discover. *e.g.: "youtube"*
            
            api_version (str): API version to discover *e.g.: "v3" not "3" and not 3*

            validate (bool): Set this to False to disallow input validation on calling methods
            
        Returns:

            aiogoogle.resource.GoogleAPI: An object that will then be used to create API requests

        Raises:

            aiogoogle.excs.HTTPError

        '''

        if api_version is None:
            # Search for name in self.list_api and return best match
            discovery_list = await self.list_api(api_name, preffered=True)

            if discovery_list['items']:
                api_name = discovery_list['items'][0]['name']
                api_version = discovery_list['items'][0]['version']
            else:
                raise ValueError('Invalid API name')
        
        request = self.discovery_service.apis.getRest(api=api_name, version=api_version, validate=False)
        if self.active_session is None:
            async with self:
                discovery_docuemnt = await self.as_anon(request)
        else:
            discovery_docuemnt = await self.as_anon(request)
        return GoogleAPI(discovery_docuemnt, validate)


    #-------- Send Requests ----------#

    async def as_user(self, *requests, timeout=None, full_resp=False):
        ''' 
        Sends requests on behalf of ``self.user_creds`` (OAuth2)
        
        Arguments:

            *requests (aiogoogle.models.Request):

                Requests objects typically created by ``aiogoogle.resource.Method.__call__``

            timeout (int):

                Total timeout for all the requests being sent

            full_resp (bool):

                If True, returns full HTTP response object instead of returning it's content

        Returns:

            aiogoogle.models.Response:
        '''
        # Refresh credentials
        if self.oauth2.is_expired(self.user_creds) is True:
            self.user_creds = self.oauth2.refresh(
                self.user_creds,
                client_creds=self.client_creds
            )

        # Authroize requests
        authorized_requests = [self.oauth2.authorize(request, self.user_creds) for request in requests]

        # Send authorized requests
        return await self.active_session.send(*authorized_requests, timeout=timeout, return_full_http_response=full_resp)

    async def as_api_key(self, *requests, timeout=None, full_resp=False):
        ''' 
        Sends requests on behalf of ``self.api_key`` (OAuth2)
        
        Arguments:

            *requests (aiogoogle.models.Request):

                Requests objects typically created by ``aiogoogle.resource.Method.__call__``

            timeout (int):

                Total timeout for all the requests being sent

            full_resp (bool):

                If True, returns full HTTP response object instead of returning it's content

        Returns:

            aiogoogle.models.Response:
        '''

        # Authorize requests
        authorized_requests = [self.api_key_manager.authorize(request, self.api_key) for request in requests]

        # Send authorized requests
        return await self.active_session.send(*authorized_requests, timeout=timeout, return_full_http_response=full_resp)

    async def as_anon(self, *requests, timeout=None, full_resp=False):
        ''' 
        Sends an unauthorized request
        
        Arguments:

            *requests (aiogoogle.models.Request):

                Requests objects typically created by ``aiogoogle.resource.Method.__call__``

            timeout (int):

                Total timeout for all the requests being sent

            full_resp (bool):

                If True, returns full HTTP response object instead of returning it's content

        Returns:

            aiogoogle.models.Response:
        '''
        return await self.active_session.send(*requests, timeout=timeout, return_full_http_response=full_resp)

    async def __aenter__(self):
        self.active_session = await self.session_factory(timeout=self.timeout).__aenter__()
        return self

    async def __aexit__(self, *args, **kwargs):
        await self.active_session.__aexit__(*args, **kwargs)
        self.active_session = None
