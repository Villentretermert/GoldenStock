"""Run from an allowed peer (allow) or a device outside the private network (deny)."""
import argparse
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument("expect", choices=["allow", "deny"])
parser.add_argument("origin")
args = parser.parse_args()
url = urlsplit(args.origin)
if (url.scheme != "https" or not url.hostname or url.username is not None or url.port not in (None,443)
        or url.path not in ("","/") or url.query or url.fragment):
    parser.error("Expected the exact private HTTPS origin")

if args.expect == "deny":
    # A certificate error or HTTP 401 still proves network reachability.
    try:
        with socket.create_connection((url.hostname,443),timeout=8):
            raise SystemExit("FAIL: TCP 443 is reachable from this device")
    except OSError:
        print("PASS: this device could not connect to the specified host on TCP 443")
else:
    root = args.origin.rstrip("/")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *unused):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),
                                         urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(root+"/health/ready",timeout=8) as response:
        if json.load(response).get("status") != "ready":
            raise SystemExit("Application is not ready")
    try:
        opener.open(root+"/api/v1/auth/me",timeout=8)
    except urllib.error.HTTPError as error:
        if error.code != 401:
            raise
    else:
        raise SystemExit("Anonymous private endpoint was accessible")
    print("PASS: trusted HTTPS, application ready, anonymous private access denied")
