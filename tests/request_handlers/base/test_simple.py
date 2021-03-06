# coding: spec

from whirlwind.request_handlers.base import Simple, Finished, reprer

from tornado.testing import AsyncHTTPTestCase
from tornado.httputil import HTTPHeaders
import tornado
import asyncio
import uuid
import json

describe AsyncHTTPTestCase, "Simple without error":
    describe "With no methods":

        def get_app(self):
            return tornado.web.Application([("/", Simple)])

        it "gets method not supported for all the methods":
            for method, body in (
                ("GET", None),
                ("POST", b""),
                ("PUT", b""),
                ("DELETE", None),
                ("PATCH", b""),
            ):
                if body is None:
                    response = self.fetch("/", method=method)
                else:
                    response = self.fetch("/", method=method, body=body)

            assert response.code == 405

    describe "Getting body as json from files":

        def get_app(self):
            self.path = "/path"

            class FilledSimple(Simple):
                async def process(s):
                    return {
                        "body": s.body_as_json(),
                        "file": s.request.files["attachment"][0]["body"].decode(),
                        "filename": s.request.files["attachment"][0]["filename"],
                    }

                do_put = process
                do_post = process

            return tornado.web.Application([(self.path, FilledSimple)])

        it "works":
            boundary = "------WebKitFormBoundaryjdGa6A5qLy18abKk"
            attachment = 'Content-Disposition: form-data; name="attachment"; filename="thing.txt"\r\nContent-Type: text/plain\r\n\r\nhello there\n'
            args = 'Content-Disposition: form-data; name="__body__"; filename="blob"\r\nContent-Type: application/json\r\n\r\n{"command":"attachments/add"}'
            body = f"{boundary}\r\n{attachment}\r\n{boundary}\r\n{args}\r\n{boundary}--"
            headers = HTTPHeaders(
                {
                    "content-type": "multipart/form-data; boundary=----WebKitFormBoundaryjdGa6A5qLy18abKk"
                }
            )

            for method in ("POST", "PUT"):
                response = self.fetch(self.path, method="POST", body=body.encode(), headers=headers)

                expected = {
                    "body": {"command": "attachments/add"},
                    "file": "hello there\n",
                    "filename": "thing.txt",
                }

                assert response.code == 200
                assert json.loads(response.body.decode()) == expected

    describe "Uses reprer":

        def get_app(self):
            self.path = "/path"
            self.result = str(uuid.uuid1())

            class Thing:
                def __special_repr__(self):
                    return {"special": "|<>THING<>|"}

            def better_reprer(o):
                if isinstance(o, Thing):
                    return o.__special_repr__()
                return reprer(o)

            class FilledSimple(Simple):
                def initialize(s, *args, **kwargs):
                    super().initialize()
                    s.reprer = better_reprer

                async def do_get(s):
                    return {"thing": Thing()}

                async def do_post(s):
                    return {"body": s.body_as_json(), "thing": Thing()}

            return tornado.web.Application([(self.path, FilledSimple)])

        it "works":
            response = self.fetch(self.path)
            assert response.code == 200
            assert json.loads(response.body.decode()) == {"thing": {"special": "|<>THING<>|"}}

            response = self.fetch(self.path, method="POST", body=json.dumps({"one": True}))
            assert response.code == 200
            assert json.loads(response.body.decode()) == {
                "thing": {"special": "|<>THING<>|"},
                "body": {"one": True},
            }

    describe "With Get":

        def get_app(self):
            self.path = "/info/blah/one/two"
            self.result = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_get(s, *, one, two):
                    assert one == "one"
                    assert two == "two"
                    assert s.request.path == "/info/blah/one/two"
                    return self.result

            return tornado.web.Application([("/info/blah/(?P<one>.*)/(?P<two>.*)", FilledSimple)])

        it "allows GET requests":
            response = self.fetch(self.path)
            assert response.code == 200
            assert response.body == self.result.encode()

    describe "With Post":

        def get_app(self):
            self.path = "/info/blah/one/two"
            self.body = str(uuid.uuid1())
            self.result = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_post(s, one, two):
                    assert one == "one"
                    assert two == "two"
                    assert s.request.path == "/info/blah/one/two"
                    assert s.request.body == self.body.encode()
                    return self.result

            return tornado.web.Application([("/info/blah/(.*)/(.*)", FilledSimple)])

        it "allows POST requests":
            response = self.fetch(self.path, method="POST", body=self.body)
            assert response.code == 200
            assert response.body == self.result.encode()

    describe "With Put":

        def get_app(self):
            self.path = "/info/blah/one/two"
            self.body = str(uuid.uuid1())
            self.result = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_put(s, *, one, two):
                    assert one == "one"
                    assert two == "two"
                    assert s.request.path == "/info/blah/one/two"
                    assert s.request.body == self.body.encode()
                    return self.result

            return tornado.web.Application([("/info/blah/(?P<one>.*)/(?P<two>.*)", FilledSimple)])

        it "allows PUT requests":
            response = self.fetch(self.path, method="PUT", body=self.body)
            assert response.code == 200
            assert response.body == self.result.encode()

    describe "With Patch":

        def get_app(self):
            self.path = "/info/blah/one/two"
            self.body = str(uuid.uuid1())
            self.result = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_patch(s, one, two):
                    assert one == "one"
                    assert two == "two"
                    assert s.request.path == "/info/blah/one/two"
                    assert s.request.body == self.body.encode()
                    return self.result

            return tornado.web.Application([("/info/blah/(.*)/(.*)", FilledSimple)])

        it "allows PATCH requests":
            response = self.fetch(self.path, method="PATCH", body=self.body)
            assert response.code == 200
            assert response.body == self.result.encode()

    describe "With Delete":

        def get_app(self):
            self.path = "/info/blah/one/two"
            self.result = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_delete(s, *, one, two):
                    assert one == "one"
                    assert two == "two"
                    assert s.request.path == "/info/blah/one/two"
                    return self.result

            return tornado.web.Application([("/info/blah/(?P<one>.*)/(?P<two>.*)", FilledSimple)])

        it "allows DELETE requests":
            response = self.fetch(self.path, method="DELETE")
            assert response.code == 200
            assert response.body == self.result.encode()

# This is so the send_msg logic in AsyncCatcher works
describe AsyncHTTPTestCase, "no ws_connection object":

    def get_app(self):
        self.path = "/info/blah"
        self.f = asyncio.Future()

        class FilledSimple(Simple):
            async def do_get(s):
                s.send_msg({"other": "stuff"})
                assert not hasattr(s, "ws_connection")
                self.f.set_result(True)
                return {"thing": "blah"}

        return tornado.web.Application([(self.path, FilledSimple)])

    it "ha no ws_connection":
        response = self.fetch(self.path)
        assert json.loads(response.body.decode()) == {"other": "stuff"}
        assert self.f.done()

describe AsyncHTTPTestCase, "Simple with error":

    def assert_correct_response(self, response, status, body):
        assert response.code == status
        assert json.dumps(body, sort_keys=True) == json.dumps(
            json.loads(response.body.decode()), sort_keys=True
        )
        assert response.headers["Content-Type"] == "application/json; charset=UTF-8"

    describe "With Get":

        def get_app(self):
            self.path = "/info/blah"
            self.reason = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_get(s):
                    assert s.request.path == "/info/blah"
                    raise Finished(status=501, reason=self.reason)

            return tornado.web.Application([(self.path, FilledSimple)])

        it "allows GET requests":
            response = self.fetch(self.path)
            self.assert_correct_response(
                response, status=501, body={"status": 501, "reason": self.reason}
            )

    describe "With Post":

        def get_app(self):
            self.path = "/info/blah"
            self.body = str(uuid.uuid1())
            self.reason = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_post(s):
                    assert s.request.path == "/info/blah"
                    assert s.request.body == self.body.encode()
                    raise Finished(status=501, reason=self.reason)

            return tornado.web.Application([(self.path, FilledSimple)])

        it "allows POST requests":
            response = self.fetch(self.path, method="POST", body=self.body)
            self.assert_correct_response(
                response, status=501, body={"status": 501, "reason": self.reason}
            )

    describe "With Put":

        def get_app(self):
            self.path = "/info/blah"
            self.body = str(uuid.uuid1())
            self.reason = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_put(s):
                    assert s.request.path == "/info/blah"
                    assert s.request.body == self.body.encode()
                    raise Finished(status=501, reason=self.reason)

            return tornado.web.Application([(self.path, FilledSimple)])

        it "allows PUT requests":
            response = self.fetch(self.path, method="PUT", body=self.body)
            self.assert_correct_response(
                response, status=501, body={"status": 501, "reason": self.reason}
            )

    describe "With Patch":

        def get_app(self):
            self.path = "/info/blah"
            self.body = str(uuid.uuid1())
            self.reason = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_patch(s):
                    assert s.request.path == "/info/blah"
                    assert s.request.body == self.body.encode()
                    raise Finished(status=501, reason=self.reason)

            return tornado.web.Application([(self.path, FilledSimple)])

        it "allows PATCH requests":
            response = self.fetch(self.path, method="PATCH", body=self.body)
            self.assert_correct_response(
                response, status=501, body={"status": 501, "reason": self.reason}
            )

    describe "With Delete":

        def get_app(self):
            self.path = "/info/blah"
            self.reason = str(uuid.uuid1())

            class FilledSimple(Simple):
                async def do_delete(s):
                    assert s.request.path == "/info/blah"
                    raise Finished(status=501, reason=self.reason)

            return tornado.web.Application([(self.path, FilledSimple)])

        it "allows DELETE requests":
            response = self.fetch(self.path, method="DELETE")
            self.assert_correct_response(
                response, status=501, body={"status": 501, "reason": self.reason}
            )
