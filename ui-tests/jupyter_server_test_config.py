"""Jupyter server config for Galata UI tests.

Disables auth + XSRF so Playwright can drive a clean lab without juggling
tokens, locks the port, and points the workspace at this directory so test
files can write fixture notebooks alongside the spec.

`configure_jupyter_server` from `jupyterlab.galata` exposes the Galata
helper hooks the JS-side `page.notebook`, `page.contents`, etc. APIs reach
into. Without that call the harness raises "Failed to activate galata
extension" on first navigation.
"""

from jupyterlab.galata import configure_jupyter_server

c = get_config()  # noqa: F821

configure_jupyter_server(c)

c.ServerApp.port = 8888
c.ServerApp.port_retries = 0
c.ServerApp.open_browser = False

c.ServerApp.token = ""
c.ServerApp.password = ""
c.ServerApp.disable_check_xsrf = True
c.LabApp.expose_app_in_browser = True
