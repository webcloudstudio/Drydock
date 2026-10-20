"""Small offline native application contracts for the supported language layouts."""

import os
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("language", ["python", "go"])
def test_native_cli_and_http_fixture(tmp_path, language):
    if language == "go":
        if shutil.which("go") is None:
            pytest.skip("Go toolchain required")
        (tmp_path / "go.mod").write_text("module example.test/native\n\ngo 1.22\n")
        (tmp_path / "app_test.go").write_text("""package native
import ("bytes"; "flag"; "fmt"; "io"; "net/http"; "net/http/httptest"; "testing")
func Run(args []string, out io.Writer) int {
 flags:=flag.NewFlagSet("app",flag.ContinueOnError)
 name:=flags.String("name","world", "name")
 if err:=flags.Parse(args);err!=nil{return 2}
 fmt.Fprintln(out,"Hello",*name);return 0
}
func NewHandler() http.Handler {
 mux:=http.NewServeMux()
 mux.HandleFunc("GET /health",func(w http.ResponseWriter,r *http.Request){fmt.Fprint(w,"ok")})
 return mux
}
func TestCLI(t *testing.T) {
 var out bytes.Buffer
 if Run([]string{"-name","Ed"},&out)!=0 || out.String()!="Hello Ed\\n" {t.Fatal(out.String())}
}
func TestHTTP(t *testing.T) {
 recorder:=httptest.NewRecorder()
 NewHandler().ServeHTTP(recorder,httptest.NewRequest("GET","/health",nil))
 if recorder.Code!=200 || recorder.Body.String()!="ok" {t.Fatal(recorder)}
}
""")
        command = ["go", "test", "./..."]
    else:
        (tmp_path / "test_app.py").write_text("""import argparse
import io
import unittest
from wsgiref.util import setup_testing_defaults

def run(args, out):
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="world")
    print("Hello", parser.parse_args(args).name, file=out)
    return 0

def app(environ, start_response):
    start_response("200 OK", [("Content-Type", "text/plain")])
    return [b"ok"]

class NativeTests(unittest.TestCase):
    def test_cli(self):
        out = io.StringIO()
        self.assertEqual(run(["--name", "Ed"], out), 0)
        self.assertEqual(out.getvalue(), "Hello Ed\\n")
    def test_http(self):
        environ = {}
        setup_testing_defaults(environ)
        statuses = []
        body = app(environ, lambda status, headers: statuses.append(status))
        self.assertEqual(statuses, ["200 OK"])
        self.assertEqual(b"".join(body), b"ok")
""")
        command = [sys.executable, "-m", "unittest", "discover"]
    result = subprocess.run(
        command,
        cwd=tmp_path,
        env={**os.environ, "GOCACHE": "/tmp/drydock-go-cache", "GOPROXY": "off"},
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
