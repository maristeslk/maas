# Copyright 2016-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""RPC helpers related to pod."""


from twisted.internet.defer import DeferredList

from maasserver.exceptions import PodProblem
from maasserver.rpc import getAllClients
from provisioningserver.rpc.cluster import (
    ComposeMachine,
    DecomposeMachine,
    DiscoverPod,
    SendPodCommissioningResults,
)
from provisioningserver.rpc.exceptions import PodActionFail, UnknownPodType
from provisioningserver.utils.twisted import (
    asynchronous,
    deferWithTimeout,
    FOREVER,
)


@asynchronous(timeout=FOREVER)
def discover_pod(pod_type, context, pod_id=None, name=None, timeout=120):
    """Discover a pod.

    :param pod_type: Type of pod to discover.
    :param context: Pod driver information to connect to pod.
    :param pod_id: ID of the pod in the database (None if new pod).
    :param name: Name of the pod in the database (None if
        new pod).

    :returns: Return a tuple with mapping of rack controller system_id and the
        discovered pod information and a mapping of rack controller
        system_id and the failure exception.
    """

    def discover(client):
        return deferWithTimeout(
            timeout,
            client,
            DiscoverPod,
            type=pod_type,
            context=context,
            pod_id=pod_id,
            name=name,
        )

    clients = getAllClients()
    dl = DeferredList(map(discover, clients), consumeErrors=True)

    def cb_results(results):
        discovered, failures = {}, {}
        for client, (success, result) in zip(clients, results):
            if success:
                discovered[client.ident] = result["pod"]
            else:
                failures[client.ident] = result.value
        return discovered, failures

    return dl.addCallback(cb_results)


def get_best_discovered_result(discovered):
    """Return the `DiscoveredPod` from `discovered` or raise an error
    if nothing was discovered or the best error return from the rack
    controlllers."""
    discovered, exceptions = discovered
    if len(discovered) > 0:
        # Return the first `DiscoveredPod`. They should all be the same.
        return list(discovered.values())[0]
    elif len(exceptions) > 0:
        # Raise the best exception that provides the most detail.
        for exc_type in [
            PodActionFail,
            NotImplementedError,
            UnknownPodType,
            None,
        ]:
            for _, exc in exceptions.items():
                if exc_type is not None:
                    if isinstance(exc, exc_type):
                        raise exc
                else:
                    raise exc
    else:
        return None


@asynchronous(timeout=120)
def send_pod_commissioning_results(
    client,
    pod_id,
    name,
    pod_type,
    system_id,
    context,
    consumer_key,
    token_key,
    token_secret,
    metadata_url,
):
    """Send commissioning results for a Pod.

    :param client: The client to use to make the RPC call.
    :param pod_id: ID of the pod in the database.
    :param name: Name of the pod in the database.
    :param pod_type: Type of pod to discover.
    :param system_id: system_id of the Node associated with the Pod.
    :param context: Pod driver information to connect to pod.
    :param consumer_key: The OAUTH consumer key for the Node.
    :param token_key: The OAUTH token key for the Node.
    :param token_secret: The OAUTH token secret for the Node.
    :param metadata_url: The metadata URL commissioning data for the Node
                         should be sent to.
    """
    d = client(
        SendPodCommissioningResults,
        pod_id=pod_id,
        name=name,
        type=pod_type,
        system_id=system_id,
        context=context,
        consumer_key=consumer_key,
        token_key=token_key,
        token_secret=token_secret,
        metadata_url=metadata_url,
    )

    def wrap_failure(failure):
        prefix = f"Unable to send commissioning results for {name}({pod_id}) because"
        if failure.check(UnknownPodType):
            raise PodProblem(f"{prefix} `{pod_type}` is an unknown Pod type.")
        elif failure.check(NotImplementedError):
            raise PodProblem(
                f"{prefix} `{pod_type}` driver does not implement the 'send_pod_commissioning_results' method."
            )
        elif failure.check(PodActionFail):
            raise PodProblem(prefix + ": " + str(failure.value))
        else:
            return failure

    d.addErrback(wrap_failure)
    return d


@asynchronous(timeout=FOREVER)
def compose_machine(client, pod_type, context, request, pod_id, name):
    """Compose a machine.

    :param client: The client to use to make the RPC call.
    :param pod_type: Type of pod to discover.
    :param context: Pod driver information to connect to pod.
    :param request: Request machine.
    :param pod_id: ID of the pod in the database.
    :param name: Name of the pod in the database.

    :returns: Returns a `DiscoveredMachine` for the newly composed machine or
        raises an exception.
    """
    d = client(
        ComposeMachine,
        type=pod_type,
        context=context,
        request=request,
        pod_id=pod_id,
        name=name,
    )
    d.addCallback(lambda result: (result["machine"], result["hints"]))

    def wrap_failure(failure):
        prefix = "Unable to compose machine because"
        if failure.check(UnknownPodType):
            raise PodProblem(
                prefix + " '%s' is an unknown pod type." % pod_type
            )
        elif failure.check(NotImplementedError):
            raise PodProblem(
                prefix
                + " '%s' driver does not implement the 'compose' method."
                % pod_type
            )
        elif failure.check(PodActionFail):
            raise PodProblem(prefix + ": " + str(failure.value))
        else:
            return failure

    d.addErrback(wrap_failure)
    return d


@asynchronous(timeout=FOREVER)
def decompose_machine(client, pod_type, context, pod_id, name):
    """Decompose a machine.

    :param client: The client to use to make the RPC call.
    :param pod_type: Type of pod to discover.
    :param context: Pod driver information with its machine context to
        connect to pod and decompose the machine.
    :param pod_id: ID of the pod in the database.
    :param name: Name of the pod in the database.

    :returns: Returns a `DiscoveredPodHints` to update the database.
    """
    d = client(
        DecomposeMachine,
        type=pod_type,
        context=context,
        pod_id=pod_id,
        name=name,
    )

    def wrap_failure(failure):
        prefix = "Unable to decompose machine because"
        if failure.check(UnknownPodType):
            raise PodProblem(
                prefix + " '%s' is an unknown pod type." % pod_type
            )
        elif failure.check(NotImplementedError):
            raise PodProblem(
                prefix
                + " '%s' driver does not implement the 'decompose' method."
                % pod_type
            )
        elif failure.check(PodActionFail):
            raise PodProblem(prefix + ": " + str(failure.value))
        else:
            return failure

    d.addCallback(lambda result: result["hints"])
    d.addErrback(wrap_failure)
    return d
