# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Twisted Application Plugin code for the MAAS Region."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )
from provisioningserver.utils.debug import (
    register_sigusr2_thread_dump_handler,
)


str = None

__metaclass__ = type
__all__ = [
    "RegionServiceMaker",
]

from twisted.application.service import IServiceMaker
from twisted.plugin import IPlugin
from twisted.python import usage
from zope.interface import implementer


def serverFromString(description):
    """Lazy import from `provisioningserver.utils.introspect`."""
    from provisioningserver.utils import introspect
    return introspect.serverFromString(description)


class Options(usage.Options):
    """Command line options for the MAAS Region Controller."""

    optParameters = [
        ["introspect", None, None,
         ("Allow introspection, allowing unhindered access to the internals "
          "of MAAS. This should probably only be used for debugging. Supply "
          "an argument in 'endpoint' form; the document 'Getting Connected "
          "with Endpoints' on the Twisted Wiki may help."),
         serverFromString],
    ]


@implementer(IServiceMaker, IPlugin)
class RegionServiceMaker:
    """Create a service for the Twisted plugin."""

    options = Options

    def __init__(self, name, description):
        self.tapname = name
        self.description = description

    def _configureLogging(self):
        # Get something going with the logs.
        from provisioningserver import logger
        logger.basicConfig()

    def _configureDjango(self):
        # Some region services use the ORM at class-load time: force Django to
        # load the models first.
        try:
            from django import setup as django_setup
        except ImportError:
            pass  # Django < 1.7
        else:
            django_setup()

    def _configureCrochet(self):
        # Prevent other libraries from starting the reactor via crochet.
        # In other words, this makes crochet.setup() a no-op.
        import crochet
        crochet.no_setup()

    def _makeIntrospectionService(self, endpoint):
        from provisioningserver.utils import introspect
        introspect_service = (
            introspect.IntrospectionShellService(
                location="region", endpoint=endpoint, namespace={}))
        introspect_service.setName("introspect")
        return introspect_service

    def makeService(self, options):
        """Construct the MAAS Region service."""
        register_sigusr2_thread_dump_handler()

        self._configureLogging()
        self._configureDjango()
        self._configureCrochet()

        # Populate the region's event-loop with services.
        from maasserver import eventloop
        eventloop.loop.populate()

        if options["introspect"] is not None:
            # Start an introspection (manhole-like) service. Attach it to the
            # eventloop's services so that it shares their lifecycle.
            introspect = self._makeIntrospectionService(options["introspect"])
            introspect.setServiceParent(eventloop.loop.services)

        # Return the eventloop's services to twistd, which will then be
        # responsible for starting them all.
        return eventloop.loop.services
