afdstats
========

A Wikipedia tool to analyze a user's history of contributions to Articles for Deletion discussions.

If you send pull requests to this repository, I'll merge them and put them up on the live version.

To install the uWSGI version on toolforge:

```
webservice stop
toolforge webservice python3.11 shell
webservice-python-bootstrap --fresh
exit
toolforge webservice python3.11 start
```

afdstats.py is served from `\www\python\src\app.py` (the afdstats.py filename is set in the `APP_NAME` constant in app.py). Static files are served from `\www\python\src\static` and requests for the root will be served `\www\python\src\static\index.html` (as set in `\www\python\uwsgi.ini`). Any other request will be served a "404 Not Found" message set in the `NOT_FOUND` constant in app.py.

See https://wikitech.wikimedia.org/wiki/Help:Toolforge/Web/Python for more information.
