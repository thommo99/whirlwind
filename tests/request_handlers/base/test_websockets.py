# coding: spec

from whirlwind.request_handlers.base import SimpleWebSocketBase, Finished, MessageFromExc
from whirlwind.server import Server, wait_for_futures
from whirlwind import test_helpers as thp

from contextlib import contextmanager
from unittest import mock
import asynctest
import asyncio
import socket
import types
import time
import uuid

class WSServer(thp.ServerRunner):
    def __init__(self, Handler):
        self.final_future = asyncio.Future()
        self.wsconnections = {}

        class WSS(Server):
            def tornado_routes(s):
                return [
                      ( "/v1/ws"
                      , Handler
                      , { "server_time": time.time()
                        , "wsconnections": self.wsconnections
                        }
                      )
                    , ( "/v1/ws_no_server_time"
                      , Handler
                      , { "server_time": None
                        , "wsconnections": self.wsconnections
                        }
                      )
                    ]

        self.server = WSS(self.final_future)
        super().__init__(self.final_future, thp.free_port(), self.server, None)

    async def after_close(self, exc_type, exc, tb):
        await wait_for_futures(self.wsconnections)

describe thp.AsyncTestCase, "SimpleWebSocketBase":
    async it "does not have server_time message if that is set to None":
        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                return "blah"

        async def doit():
            message_id = str(uuid.uuid1())
            async with WSServer(Handler) as server:
                connection = await server.ws_connect(skip_hook=True, path="/v1/ws_no_server_time")
                await server.ws_write(connection
                    , {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
                    )
                res = await server.ws_read(connection)
                self.assertEqual(res, {"reply": "blah", "message_id": message_id})

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    @thp.with_timeout
    async it "can modify what comes from a progress message":
        class Handler(SimpleWebSocketBase):
            def transform_progress(self, body, message, **kwargs):
                yield {"body": body, "message": message, "kwargs": kwargs}

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                progress_cb("WAT", arg=1, do_log=False, stack_extra=1)
                return "blah"

        message_id = str(uuid.uuid1())
        async with WSServer(Handler) as server:
            connection = await server.ws_connect()
            msg = {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
            await server.ws_write(connection, msg)

            res = await server.ws_read(connection)
            progress = {"body": msg, "message": "WAT", "kwargs": {"arg": 1, "do_log": False, "stack_extra": 1}}
            self.assertEqual(res, {"reply": {"progress": progress}, "message_id": message_id})

            res = await server.ws_read(connection)
            self.assertEqual(res, {"reply": "blah", "message_id": message_id})

            connection.close()
            self.assertIs(await server.ws_read(connection), None)

    @thp.with_timeout
    async it "can yield 0 progress messages if we so desire":
        class Handler(SimpleWebSocketBase):
            def transform_progress(self, body, message, **kwargs):
                if message == "ignore":
                    return
                yield message

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                progress_cb("hello")
                progress_cb("ignore")
                progress_cb("there")
                return "blah"

        message_id = str(uuid.uuid1())
        async with WSServer(Handler) as server:
            connection = await server.ws_connect()
            msg = {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
            await server.ws_write(connection, msg)

            async def assertProgress(expect):
                self.assertEqual(await server.ws_read(connection)
                    , {"reply": {"progress": expect}, "message_id": message_id}
                    )

            await assertProgress("hello")
            await assertProgress("there")

            res = await server.ws_read(connection)
            self.assertEqual(res, {"reply": "blah", "message_id": message_id})

            connection.close()
            self.assertIs(await server.ws_read(connection), None)

    @thp.with_timeout
    async it "can yield multiple progress messages if we so desire":
        class Handler(SimpleWebSocketBase):
            def transform_progress(self, body, message, **kwargs):
                for m in message:
                    yield m

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                progress_cb(["hello", "people"])
                return "blah"

        message_id = str(uuid.uuid1())
        async with WSServer(Handler) as server:
            connection = await server.ws_connect()
            msg = {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
            await server.ws_write(connection, msg)

            async def assertProgress(expect):
                self.assertEqual(await server.ws_read(connection)
                    , {"reply": {"progress": expect}, "message_id": message_id}
                    )

            await assertProgress("hello")
            await assertProgress("people")

            res = await server.ws_read(connection)
            self.assertEqual(res, {"reply": "blah", "message_id": message_id})

            connection.close()
            self.assertIs(await server.ws_read(connection), None)

    @thp.with_timeout
    async it "calls the message_done callback":
        info = {"message_key": None}
        called = []

        class Handler(SimpleWebSocketBase):
            def message_done(self, request, final, message_key, exc_info=None):
                called.append((request, final, message_key, exc_info))

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                info["message_key"] = message_key
                called.append("process")
                progress_cb("hello")
                return "blah"

        message_id = str(uuid.uuid1())
        async with WSServer(Handler) as server:
            connection = await server.ws_connect()
            msg = {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
            await server.ws_write(connection, msg)

            self.assertEqual(await server.ws_read(connection)
                , {"reply": {"progress": "hello"}, "message_id": message_id}
                )

            res = await server.ws_read(connection)
            self.assertEqual(res, {"reply": "blah", "message_id": message_id})

            assert info["message_key"] is not None
            self.assertEqual(called
                , [ "process"
                  , (msg, "blah", info["message_key"], None)
                  ]
                )

            connection.close()
            self.assertIs(await server.ws_read(connection), None)

    @thp.with_timeout
    async it "calls the message_done with exc_info if an exception is raised in process_message":
        info = {"message_key": None}
        error = ValueError("NOPE")
        called = []

        class Handler(SimpleWebSocketBase):
            def message_done(self, request, final, message_key, exc_info=None):
                called.append((request, final, message_key, exc_info))

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                info["message_key"] = message_key
                called.append("process")
                progress_cb("hello")
                raise error

        message_id = str(uuid.uuid1())
        async with WSServer(Handler) as server:
            connection = await server.ws_connect()
            msg = {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
            await server.ws_write(connection, msg)

            self.assertEqual(await server.ws_read(connection)
                , {"reply": {"progress": "hello"}, "message_id": message_id}
                )

            res = await server.ws_read(connection)
            reply = {"error": "Internal Server Error", "error_code": "InternalServerError", "status": 500}
            self.assertEqual(res, {"reply": reply, "message_id": message_id})

            assert info["message_key"] is not None

            class ATraceback:
                def __eq__(self, other):
                    return isinstance(other, types.TracebackType)

            self.assertEqual(called
                , [ "process"
                  , (msg, reply, info["message_key"], (ValueError, error, ATraceback()))
                  ]
                )

            connection.close()
            self.assertIs(await server.ws_read(connection), None)

    @thp.with_timeout
    async it "message_done can be used to close the connection":
        info = {"message_key": None}
        error = ValueError("NOPE")
        called = []

        class Handler(SimpleWebSocketBase):
            def message_done(self, request, final, message_key, exc_info=None):
                called.append((request, final, message_key, exc_info))
                self.close()

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                info["message_key"] = message_key
                called.append("process")
                progress_cb("there")
                return {"one": "two"}

        message_id = str(uuid.uuid1())
        async with WSServer(Handler) as server:
            connection = await server.ws_connect()
            msg = {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
            await server.ws_write(connection, msg)

            self.assertEqual(await server.ws_read(connection)
                , {"reply": {"progress": "there"}, "message_id": message_id}
                )

            res = await server.ws_read(connection)
            self.assertEqual(res, {"reply": {"one": "two"}, "message_id": message_id})

            assert info["message_key"] is not None

            self.assertEqual(called
                , [ "process"
                  , (msg, {"one": "two"}, info["message_key"], None)
                  ]
                )

            self.assertIs(await server.ws_read(connection), None)

    async it "modifies ws_connection object":
        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                self.assertEqual(type(self.key), str)
                self.assertEqual(len(self.key), 36)
                self.assertNotEqual(message_id, message_key)
                self.assertNotEqual(message_key, self.key)
                assert message_key in self.wsconnections
                return "blah"

        async def doit():
            message_id = str(uuid.uuid1())
            async with WSServer(Handler) as server:
                connection = await server.ws_connect()
                await server.ws_write(connection
                    , {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
                    )
                res = await server.ws_read(connection)
                self.assertEqual(server.wsconnections, {})

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "waits for connections to close before ending server":
        f1 = asyncio.Future()
        f2 = asyncio.Future()

        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                f1.set_result(True)
                await asyncio.sleep(0.5)
                f2.set_result(True)
                return "blah"

        async def doit():
            message_id = str(uuid.uuid1())

            async with WSServer(Handler) as server:
                connection = await server.ws_connect()
                await server.ws_write(connection
                    , {"path": "/one/two", "body": {"hello": "there"}, "message_id": message_id}
                    )
                await self.wait_for(f1)
                self.assertEqual(len(server.wsconnections), 1)
                assert not f2.done()

            self.assertEqual(len(server.wsconnections), 0)
            self.assertEqual(f2.result(), True)

        await self.wait_for(doit())

    async it "can stay open":
        message_info = {"keys": set(), "message_keys": []}

        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                self.assertEqual(path, "/one/two")
                self.assertEqual(body, {"wat": mock.ANY})
                message_info["keys"].add(s.key)
                message_info["message_keys"].append(message_key)
                return body["wat"]

        async def doit():
            message_id = str(uuid.uuid1())

            async with WSServer(Handler) as server:
                connection = await server.ws_connect()
                await server.ws_write(connection
                    , {"path": "/one/two", "body": {"wat": "one"}, "message_id": message_id}
                    )
                res = await server.ws_read(connection)
                self.assertEqual(res["message_id"], message_id)
                self.assertEqual(res["reply"], "one")

                await server.ws_write(connection
                    , {"path": "/one/two", "body": {"wat": "two"}, "message_id": message_id}
                    )
                res = await server.ws_read(connection)
                self.assertEqual(res["message_id"], message_id)
                self.assertEqual(res["reply"], "two")

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

        self.assertEqual(len(message_info["keys"]), 1)
        self.assertEqual(len(message_info["message_keys"]), len(set(message_info["message_keys"])))

    async it "can handle ticks for me":
        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                self.assertEqual(path, "/one/two")
                self.assertEqual(body, {"wat": mock.ANY})
                return body["wat"]

        async def doit():
            message_id = str(uuid.uuid1())

            async with WSServer(Handler) as server:
                connection = await server.ws_connect()
                await server.ws_write(connection
                    , {"path": "__tick__", "message_id": "__tick__"}
                    )
                res = await server.ws_read(connection)
                self.assertEqual(res["message_id"], "__tick__")
                self.assertEqual(res["reply"], {"ok": "thankyou"})

                await server.ws_write(connection
                    , {"path": "/one/two", "body": {"wat": "two"}, "message_id": message_id}
                    )
                res = await server.ws_read(connection)
                self.assertEqual(res["message_id"], message_id)
                self.assertEqual(res["reply"], "two")

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "complains if the message is incorrect":
        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                return "processed"

        async def doit():
            invalid = [
                  {"message_id": "just_message_id"}
                , {"message_id": "no_path", "body": {}}
                , {"path": "/no/message_id", "body": {}}
                , {"path": "/no/body", "message_id": "blah"}
                , {}
                , ""
                , "asdf"
                , False
                , True
                , 0
                , 1
                , []
                , [1]
                ]

            async with WSServer(Handler) as server:
                connection = await server.ws_connect()

                for body in invalid:
                    await server.ws_write(connection, body)
                    res = await server.ws_read(connection)
                    assert res is not None, "Got no reply to : '{}'".format(body)
                    self.assertEqual(res["message_id"], None)
                    assert "reply" in res
                    assert "error" in res["reply"]

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "can do multiple messages at the same time":
        class Handler(SimpleWebSocketBase):
            do_close = False

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                progress_cb({body["serial"]: ["info", "start"]})
                await asyncio.sleep(body["sleep"])
                return {"processed": body["serial"]}

        async def doit():
            async with WSServer(Handler) as server:
                connection = await server.ws_connect()

                msg_id1 = str(uuid.uuid1())
                msg_id2 = str(uuid.uuid1())

                await server.ws_write(connection
                    , {"path": "/process", "body": {"serial": "1", "sleep": 0.1}, "message_id": msg_id1}
                    )
                await server.ws_write(connection
                    , {"path": "/process", "body": {"serial": "2", "sleep": 0.05}, "message_id": msg_id2}
                    )

                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id1, "reply": {"progress": {"1": ["info", "start"]}}}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id2, "reply": {"progress": {"2": ["info", "start"]}}}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id2, "reply": {"processed": "2"}}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id1, "reply": {"processed": "1"}}
                    )

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "can close the websocket if we return self.Closing":
        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                if body["close"]:
                    return s.Closing
                else:
                    return "stillalive"

        async def doit():
            async with WSServer(Handler) as server:
                connection = await server.ws_connect()

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/process", "body": {"close": False}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id, "reply": "stillalive"}
                    )

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/process", "body": {"close": False}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id, "reply": "stillalive"}
                    )

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/process", "body": {"close": True}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id, "reply": {"closing": "goodbye"}}
                    )

                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "can handle arbitrary json for the body":
        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                return body

        async def doit():
            async with WSServer(Handler) as server:
                connection = await server.ws_connect()

                msg_id = str(uuid.uuid1())
                body = {
                      "one": "two"
                    , "three": 4
                    , "five": ["six", "seven", []]
                    , "six": []
                    , "seven": True
                    , "eight": False
                    , "nine": {"one": "two", "three": None, "four": {"five": "six"}}
                    }

                await server.ws_write(connection
                    , {"path": "/process", "body": body, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , {"message_id": msg_id, "reply": body}
                    )
                connection.close()

                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "can handle exceptions in process_message":
        class BadError(Exception):
            def as_dict(self):
                return {"error": str(self)}

        errors = {"one": ValueError("lolz"), "two": BadError("Try again")}

        class Handler(SimpleWebSocketBase):
            def initialize(self, *args, **kwargs):
                super().initialize(*args, **kwargs)

                def message_from_exc(exc_type, exc, tb):
                    if hasattr(exc, "as_dict"):
                        return {"error_code": exc_type.__name__, "error": exc.as_dict()}
                    else:
                        return MessageFromExc()(exc_type, exc, tb)

                self.message_from_exc = message_from_exc

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                raise errors[body["error"]]

        async def doit():
            async with WSServer(Handler) as server:
                connection = await server.ws_connect()

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/error", "body": {"error": "one"}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , { "message_id": msg_id
                      , "reply":
                        { "error": "Internal Server Error"
                        , "error_code": "InternalServerError"
                        , "status": 500
                        }
                      }
                    )

                msg_id2 = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/error", "body": {"error": "two"}, "message_id": msg_id2}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , { "message_id": msg_id2
                      , "reply":
                        { "error": {"error": "Try again"}
                        , "error_code": "BadError"
                        }
                      }
                    )

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "can handle a return that has as_dict on it":
        class Ret:
            def __init__(s, value):
                s.value = value

            def as_dict(s):
                return {"result": "", "value": s.value}

        class Handler(SimpleWebSocketBase):
            async def process_message(s, path, body, message_id, message_key, progress_cb):
                return Ret("blah and stuff")

        async def doit():
            async with WSServer(Handler) as server:
                connection = await server.ws_connect()

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/thing", "body": {}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , { "message_id": msg_id
                      , "reply": {"result": "", "value": "blah and stuff"}
                      }
                    )

                connection.close()
                self.assertIs(await server.ws_read(connection), None)

        await self.wait_for(doit())

    async it "can process replies":
        replies = []

        error1 = ValueError("Bad things happen")
        error2 = Finished(status=400, error="Stuff")

        class Handler(SimpleWebSocketBase):
            def process_reply(self, msg, exc_info=None):
                replies.append((msg, exc_info))

            async def process_message(s, path, body, message_id, message_key, progress_cb):
                if path == "/no_error":
                    return {"success": True}
                elif path == "/internal_error":
                    raise error1
                elif path == "/custom_return":
                    s.reply({"progress": {"error": "progress"}}, message_id=message_id)

                    class Ret:
                        def as_dict(s):
                            return MessageFromExc()(type(error2), error2, None)

                        @property
                        def exc_info(s):
                            return (type(error2), error2, None)

                    return Ret()

        async def doit():
            async with WSServer(Handler) as server:
                connection = await server.ws_connect()

                ##################
                ### NO_ERROR

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/no_error", "body": {}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , { "message_id": msg_id
                      , "reply": {"success": True}
                      }
                    )

                ##################
                ### INTERNAL_ERROR

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/internal_error", "body": {}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , { "message_id": msg_id
                      , "reply": {"error": "Internal Server Error", "error_code": "InternalServerError", "status": 500}
                      }
                    )

                ##################
                ### CUSTOM RETURN

                msg_id = str(uuid.uuid1())
                await server.ws_write(connection
                    , {"path": "/custom_return", "body": {}, "message_id": msg_id}
                    )
                self.assertEqual(await server.ws_read(connection)
                    , { "message_id": msg_id
                      , "reply": {"progress": {"error": "progress"}}
                      }
                    )
                self.assertEqual(await server.ws_read(connection)
                    , { "message_id": msg_id
                      , "reply": {"error": "Stuff", "status": 400}
                      }
                    )

        await self.wait_for(doit())

        class ATraceback:
            def __eq__(self, other):
                return isinstance(other, types.TracebackType)

        self.maxDiff = None

        self.assertEqual(replies
            , [ ( {'success': True}
                , None
                )
              , ( {'status': 500, 'error': 'Internal Server Error', 'error_code': 'InternalServerError'}
                , (ValueError, error1, ATraceback())
                )
              , ( {'progress': {'error': 'progress'}}
                , None
                )
              , ( {'error': "Stuff", "status": 400}
                , (Finished, error2, None)
                )
              ]
            )
