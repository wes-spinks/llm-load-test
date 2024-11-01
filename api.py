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

from datetime import datetime
from flask import Flask, Response, jsonify, make_response, request, render_template
from jinja2 import Environment, FileSystemLoader

from llm_load_test import load_test
from llm_load_test.performance_visualization import visualize

APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = os.environ.get("APP_PORT", "8443")

LOG_FMT = "[%(asctime)s] [%(process)d] [%(levelname)s] %(message)s"
LOG_DATE_FMT = "%Y-%m-%d %H:%M:%S %z"
logging.basicConfig(
    format=LOG_FMT,
    datefmt=LOG_DATE_FMT,
    stream=sys.stdout,
    level=logging.INFO,
)

app = Flask(__name__, static_url_path="/static")
app.logger.setLevel(os.environ.get("LOGGING_LEVEL", "INFO"))
unverified_context = ssl._create_unverified_context()  # pylint: disable=W0212


def new_uuid() -> str:
    _new = uuid.uuid4()
    return str(_new)


@app.route("/health", methods=["GET"])
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

    if not data.get("plugin_options").get("host"):
        return make_response(jsonify(content), 400)
    data["uuid"] = content["details"] = new_uuid()
    app.logger.info(f"Beginning load test for: {data['uuid']}")

    def _custom_config(data) -> str:
        env = Environment(loader=FileSystemLoader("llm_load_test/templates"))
        template = env.get_template("llt_config_template.j2")
        rendered_template = template.render(data)
        try:
            os.mkdir(f"/opt/app-root/src/llm_load_test/static/{data['uuid']}")
        except FileExistsError:
            pass
        outpath = f"llm_load_test/static/{data['uuid']}/config.yaml"
        with open(outpath, "w") as configout:
            configout.write(rendered_template)
        return outpath

    def _create_visual(uuid: str):
        visualize(uuid)
        app.logger.info(f"VISUALIZED: {uuid}")

    def test_and_visualize(data: str):
        uuid = data["uuid"]
        cfgpath = _custom_config(data)
        app.logger.info(f"CONFIG GENERATED: {cfgpath}")
        try:
            load_test.main(["-c", f"{cfgpath}", "-u", uuid])
        except SystemExit as err:
            os.rmdir(f"/opt/app-root/src/llm_load_test/static/{data['uuid']}")
            return False
        _create_visual(uuid)
        return True

    try:
        test_success = test_and_visualize(data)
        if not test_success:
            content[
                "details"
            ] = "Error during {} load tests. Deleted results.".format(
                str(data["plugin_options"]["host"])
            )
            return content
        content["url"] = f"/view/{data['uuid']}"
        content["status"] = "success"
    except FileNotFoundError as err:
        content["details"] = str(err)
    app.logger.info(f"""request: {data}; init output: {content}""")
    return make_response(jsonify(content), 202)


def list_existing(basedir: str = "llm_load_test/static"):
    files = []
    for name in os.listdir(basedir):
        if os.path.isdir(f"{basedir}/{name}"):
            modtime = datetime.fromtimestamp(
                os.path.getmtime(f"{basedir}/{name}")
            ).strftime("%Y-%m-%d %H:%M:%S")
            test = (name, modtime)
            files.append(test)
    return render_template("static_view.html", files=files, basedir=basedir)


@app.route("/view/<string:uuid>", methods=["GET"])
def view_test(uuid):
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
    app.logger.info(f"""request: {uuid}""")
    if uuid == "list":
        return list_existing()

    ret = {"status": "Error", "message": "Requires UUID"}
    if not uuid:
        return make_response(jsonify(ret), 400)
    if not is_valid_uuid(uuid):
        message = "Request requires valid uuid as path param (e.g. view/<uuid>)"
        return make_response(jsonify(ret), 400)

    test_path = f"llm_load_test/static/{uuid}"
    out = urllib.request.urlopen(
        f"file:///opt/app-root/src/llm_load_test/static/{uuid}/output.json"
    )
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
    <p>Go to <a href='/static/{uuid}/config.yaml' target="_blank">/static/{uuid}/config.yaml</a> to download config.yaml</p>
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
