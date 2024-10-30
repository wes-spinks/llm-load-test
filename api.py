import flask
import json
import logging
import os
import ssl
import urllib.request
import uuid
from typing import Any, Optional
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, Response, jsonify, make_response, request

from llm_load_test import load_test
from llm_load_test.performance_visualization import visualize

APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = os.environ.get("APP_PORT", "8443")
KUBERNETES_HOST = os.environ.get("KUBERNETES_SERVICE","localhost")

LOG_FMT = "[%(asctime)s] [%(process)d] [%(levelname)s] %(message)s"
LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S %z"
logging.basicConfig(
    format=LOG_FMT,
    datefmt=LOG_DATE_FMT,
    stream=sys.stdout,
    level=logging.DEBUG,
)

app = Flask(__name__, static_url_path="/static")
app.logger.setLevel(os.environ.get("LOGGING_LEVEL", "DEBUG"))
unverified_context = ssl._create_unverified_context()  # pylint: disable=W0212
app.logger.info(f"LLM Load Test API service running on '{KUBERNETES_HOST}'")

def new_uuid() -> str:
    _new = uuid.uuid4()
    return str(_new)


@app.route("/health")
def ready():
    """Simple health check to confirm app is responding

    Returns:
        str: literal "OK"
    """
    return "OK"


@app.route("/init-test", methods=["POST"])
def begin_load_test():
    """Endpoint to initialize load test with params from providing config dict

    Arguments:
        config (dict): llm-load-test config.yaml object

    Returns:
        dict: with status, url, (optional) details keys
          status[str]:
            one of the following states: "success" "failed" "error" "exception"
          url[str]:
            view url containing uuid of test job
          Details(optional)[obj]:
            Extra request/response information
    """
    content = {"status": "error", "url": "", "details": "Requires 'host' key/value"}
    data = request.get_json()
    
    if "host" not in data:
        return make_response(jsonify(content), 400)
    data["uuid"] = content["details"] = new_uuid()
    app.logger.info(f"Beginning load test for: {data['uuid']}")

    def _create_visual(uuid: str):
        visualize(uuid)
        app.logger.info(f"Created visual for {data['uuid']}")

    def test_and_visualize(uuid: str):
        load_test.main(["-c", "llm_load_test/config.yaml", "-u", uuid])
        _create_visual(uuid)

    test_and_visualize(data["uuid"])
    content["url"] = f"view/{data['uuid']}"
    content["status"] = "success"
    app.logger.info(f"""request: {data}; init output: {content}""")
    return make_response(jsonify(content), 202)


@app.route("/view", methods=["GET", "POST"])
def view_test():
    """Endpoint to view HTML of a completed test

    Arguments:
        uuid (str): uuid of init-test response
    Returns:
        html: containing output.json and image
          output[dict]:
            generated output.json contents
          image[obj]:
            performance visualization image
    """
    uuid = request.args.get("uuid")
    app.logger.info(f"""request: {uuid}""")

    ret = {"status": "Error", "message": "Request requires valid uuid as path param"}
    if not is_valid_uuid(uuid):
        return make_response(jsonify(ret), 400)
    if not uuid:
        return make_response(jsonify(ret), 400)

    test_path = f"llm_load_test/static/{uuid}"
    out = urllib.request.urlopen(f"http://localhost:8443/static/{uuid}/output.json")
    outputjson = json.loads(out.read())

    templ = f"""
    <html><body>
    <h2 style='color: red;'>{uuid}</h2>
    <h4 style='color: green;'>Performance Visualization</h4><p>
    <a href='/static/{uuid}/image.png'>
      <img src='/static/{uuid}/image.png'></img><p>
    </a>
    <br>
    <details>
      <summary>llm_load_test: output.json content</summary>
      <p>
      <div>
        <code> 
        {outputjson}
        <code>
      </div>
      </p>
    </details>
    <br>
    <p>Go to <a href='/static/{uuid}/output.json'>/static/{uuid}/output.json</a> for non-HTML (output JSON only)</p>
    <p>Go to <a href='/static/{uuid}/image.png'>/static/{uuid}/image.png</a> for image only</p>
    </body></html>
    """
    ret = {"status": "success", "message": "html returned"}
    app.logger.info(f"""{uuid}: output: {ret}""")
    return make_response(templ, 200)


def is_valid_uuid(val):
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    app.run(host=APP_HOST, port=APP_PORT, debug=True)
