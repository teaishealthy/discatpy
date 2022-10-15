"""
The MIT License (MIT)

Copyright (c) 2022-present EmreTech

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from .cache import ClientCache
from .flags import Intents
from .gateway import GatewayClient
from .http import HTTPClient
from .internal.dispatcher import Dispatcher
from .types.snowflake import *
from .user import User

if TYPE_CHECKING:
    from typing import Union

    from .channel import RawChannel
    from .guild import Guild

    DiscordModel = Union[RawChannel, Guild, User]

__all__ = ("Client",)


def _fetch_function_from_type(http: HTTPClient, t: Union[type, str]):
    t_name: str = ""
    t_name = t.__name__.lower() if isinstance(t, type) else t.lower()
    if "channel" in t_name:
        return http.get_channel
    elif t_name == "guild":
        return http.get_guild
    elif t_name == "user":
        return http.get_user
    else:
        raise TypeError("invalid type passed in")


class Client:
    """
    The main client that joins the developer's code and the Discord API together.

    Parameters
    ----------
    api_version: :type:`Optional[int]`
        The api version of the HTTP Client.
        This is automatically set to `None`, which will be set to `9`.

    Attributes
    ----------
    gateway: :type:`Optional[GatewayClient]`
        The gateway client that handles connections with the gateway
    http: :type:`HTTPClient`
        The http client that handles connections with the REST API
    cache: :type:`ClientCache`
        The client's internal cache used for storing objects from the API/Gateway.
    me: :type:`User`
        The bot user
    running: :type:`bool`
        Whether or not the client is running
    intents: :type:`int`
        The intents for the gateway
    dispatcher: :type:`Dispatcher`
        The event dispatcher for Gateway events
    """

    __slots__ = (
        "gateway",
        "http",
        "cache",
        "me",
        "running",
        "intents",
        "dispatcher",
    )

    def __init__(self, /, intents: Intents, api_version: Optional[int] = None):
        self.gateway: Optional[GatewayClient] = None  # initalized later
        self.http: HTTPClient = HTTPClient(api_version=api_version)
        self.cache: ClientCache = ClientCache(self)
        self.me: Optional[User] = None
        self._gateway_reconnect = asyncio.Event()
        self.running: bool = False
        self.intents: Intents = intents
        self.dispatcher: Dispatcher = Dispatcher()

    @property
    def token(self):
        """
        The bot's token.
        Shortcut for :attr:`Client.http.token`.
        """
        return self.http.token

    @property
    def api_version(self):
        """
        The api version the HTTP Client is using.
        Shortcut for :attr:`Client.http.api_version`.
        """
        return self.http.api_version

    # Events/listeners

    def event(self, name: Optional[str] = None):
        """A decorator that registers a function as an event callback.

        Parameters
        ----------
        name: :type:`Optional[str]` = `None`
            The name of this event. If none, then the function's name is used.
        """

        def decorator(func):
            self.dispatcher.set_event(func, name)
            return func

        return decorator

    def listener(self, name: Optional[str] = None):
        """A decorator that registers a function as a listener for an event.

        You should use this decorator if you have multiple functions for one event.

        Parameters
        ----------
        name: :type:`Optional[str]` = `None`
            The name of this listener. If none, then the function's name is used.
        """

        def decorator(func):
            self.dispatcher.add_listener(func, name)
            return func

        return decorator

    # Running logic

    async def login(self, token: str):
        """
        Logs into the bot user and grabs its user object.

        Do not run this yourself. `run()` will take care of this for you.

        Parameters
        ----------
        token: :type:`str`
            The token for the bot user
        """
        user_dict = await self.http.login(token)
        self.me = User(user_dict, self)
        self.cache.add_user(self.me)

    async def _end_run(self):
        await self.gateway.close(reconnect=False)
        await self.http.close()

    async def gateway_run(self):
        """
        Runs the Gateway Client code and reconnects when prompted.

        Do not run this yourself. `run()` will take care of this for you.
        """
        gateway_url = await self.http.get_gateway_bot()
        gateway_url = gateway_url[1]
        self.gateway = GatewayClient(await self.http.ws_connect(gateway_url), self)
        self.running = True

        while self.running:
            try:
                await self.gateway.loop()

                # if we get here, then we probably have to reconnect
                if self._gateway_reconnect.is_set():
                    self.gateway.ws = await self.http.ws_connect(gateway_url)
                    self._gateway_reconnect.clear()
                else:
                    # we cannot reconnect, so we must stop the program
                    self.running = False
            except Exception as e:
                await self.dispatcher.dispatch("on_error", e)

    def run(self, token: str):
        """
        Logs into the bot user then starts the Gateway client.

        Parameters
        ----------
        token: :type:`str`
            The token for the bot user
        """

        async def wrapped():
            await self.login(token)
            await self.gateway_run()

        try:
            asyncio.run(wrapped())
        except KeyboardInterrupt:
            pass
        finally:
            asyncio.run(self._end_run())

    # Cache/HTTP

    def grab(self, id: Snowflake, _type: Union[DiscordModel, str]):
        """Grabbing an object is attempting to get it from the cache then fetching it from
        the API if it doesn't exist in the cache.

        Parameters
        ----------
        id: :type:`Snowflake`
            The id of the object to grab.
        _type: :type:`type`
            The type of the object to grab.
        """
        obj = self.cache.get_type(id, _type)

        if obj is None:
            fetch_func = _fetch_function_from_type(_type)
            d = asyncio.get_event_loop().run_in_executor(fetch_func(id))
            obj = _type(d, self)

        return obj
