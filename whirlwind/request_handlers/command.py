from whirlwind.request_handlers.base import Simple, SimpleWebSocketBase

import logging
import inspect

log = logging.getLogger("whirlwind.request_handlers.command")

class ProgressMessageMaker:
    def __init__(self, stack_level=0):
        frm = inspect.stack()[1 + stack_level]
        mod = inspect.getmodule(frm[0])
        self.logger_name = mod.__name__

    def __call__(self, body, message, do_log=True, **kwargs):
        info = self.make_info(body, message, **kwargs)
        if do_log:
            self.do_log(body, message, info, **kwargs)
        return info

    def make_info(self, body, message, **kwargs):
        info = {}

        if isinstance(message, Exception):
            info["error_code"] = message.__class__.__name__
            if hasattr(message, "as_dict"):
                info["error"] = message.as_dict()
            else:
                info["error"] = str(message)
        elif message is None:
            info["done"] = True
        else:
            info["info"] = message

        info.update(kwargs)
        return info

    def do_log(self, body, message, info, **kwargs):
        pass

class ProcessReplyMixin:
    def process_reply(self, msg, exc_info=None):
        try:
            self.commander.process_reply(msg, exc_info)
        except KeyboardInterrupt:
            raise
        except Exception as error:
            log.exception(error)

class CommandHandler(Simple, ProcessReplyMixin):
    def initialize(self, commander, progress_maker=None):
        self.commander = commander
        self.progress_maker = progress_maker or ProgressMessageMaker

    async def do_put(self):
        j = self.body_as_json()

        def progress_cb(message, stack_extra=0, **kwargs):
            maker = self.progress_maker(1 + stack_extra)
            info = maker(j, message, **kwargs)
            self.process_reply(info)

        path = self.request.path
        while path and path.endswith("/"):
            path = path[:-1]

        return await self.commander.execute(path, j, progress_cb, self)

class WSHandler(SimpleWebSocketBase, ProcessReplyMixin):
    def initialize(self, server_time, wsconnections, commander, progress_maker=None):
        self.commander = commander
        self.progress_maker = progress_maker or ProgressMessageMaker
        super().initialize(server_time, wsconnections)

    async def process_message(self, path, body, message_id, progress_cb):
        def pcb(message, stack_extra=0, **kwargs):
            maker = self.progress_maker(1 + stack_extra)
            info = maker(body, message, **kwargs)
            progress_cb(info)

        return await self.commander.execute(path, body, pcb, self)