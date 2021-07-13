# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""URL routing configuration."""


from django.conf.urls import include, url
from django.contrib.auth.decorators import user_passes_test
from django.http import HttpResponse

from maasserver import urls_api
from maasserver.bootresources import (
    simplestreams_file_handler,
    simplestreams_stream_handler,
)
from maasserver.macaroon_auth import MacaroonDischargeRequest
from maasserver.prometheus.stats import prometheus_stats_handler
from maasserver.views import TextTemplateView
from maasserver.views.account import authenticate, csrf, login, logout
from maasserver.views.rpc import info


def adminurl(regexp, view, *args, **kwargs):
    view = user_passes_test(lambda u: u.is_superuser)(view)
    return url(regexp, view, *args, **kwargs)


# Anonymous views.
urlpatterns = [
    url(r"^accounts/login/$", login, name="login"),
    url(r"^accounts/authenticate/$", authenticate, name="authenticate"),
    url(
        r"^accounts/discharge-request/$",
        MacaroonDischargeRequest(),
        name="discharge-request",
    ),
    url(
        r"^images-stream/streams/v1/(?P<filename>.*)$",
        simplestreams_stream_handler,
        name="simplestreams_stream_handler",
    ),
    url(
        r"^images-stream/(?P<os>.*)/(?P<arch>.*)/(?P<subarch>.*)/"
        "(?P<series>.*)/(?P<version>.*)/(?P<filename>.*)$",
        simplestreams_file_handler,
        name="simplestreams_file_handler",
    ),
    url(r"^metrics$", prometheus_stats_handler, name="metrics"),
    url(
        r"^robots\.txt$",
        TextTemplateView.as_view(template_name="maasserver/robots.txt"),
        name="robots",
    ),
]

# # URLs for logged-in users.
# Preferences views.
urlpatterns += [url(r"^account/csrf/$", csrf, name="csrf")]
# Logout view.
urlpatterns += [url(r"^accounts/logout/$", logout, name="logout")]

# API URLs. If old API requested, provide error message directing to new API.
urlpatterns += [
    url(r"^api/2\.0/", include(urls_api)),
    url(
        r"^api/version/",
        lambda request: HttpResponse(content="2.0", content_type="text/plain"),
        name="api_version",
    ),
    url(
        r"^api/1.0/",
        lambda request: HttpResponse(
            content_type="text/plain",
            status=410,
            content="The 1.0 API is no longer available. "
            "Please use API version 2.0.",
        ),
        name="api_v1_error",
    ),
]


# RPC URLs.
urlpatterns += [url(r"^rpc/$", info, name="rpc-info")]
