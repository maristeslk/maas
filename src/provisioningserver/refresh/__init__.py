# Copyright 2016-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functionality to refresh rack controller hardware and networking details."""

import copy
import os
from subprocess import DEVNULL, PIPE, Popen, TimeoutExpired
import tempfile

from provisioningserver.logger import get_maas_logger
from provisioningserver.refresh.maas_api_helper import (
    capture_script_output,
    MD_VERSION,
    signal,
    SignalException,
)
from provisioningserver.refresh.node_info_scripts import (
    LXD_OUTPUT_NAME,
    NODE_INFO_SCRIPTS,
)
from provisioningserver.utils.shell import call_and_check, ExternalProcessError
from provisioningserver.utils.snappy import get_snap_path, running_in_snap
from provisioningserver.utils.twisted import synchronous

maaslog = get_maas_logger("refresh")


def get_architecture():
    """Get the architecture of the running system."""
    try:
        stdout = call_and_check("archdetect").decode("utf-8")
    except ExternalProcessError:
        return ""
    arch, subarch = stdout.strip().split("/")
    if arch in ["i386", "amd64", "arm64", "ppc64el"]:
        subarch = "generic"
    return "%s/%s" % (arch, subarch)


def signal_wrapper(*args, **kwargs):
    """Wrapper to capture and log any SignalException from signal."""
    try:
        signal(*args, **kwargs)
    except SignalException as e:
        maaslog.error("Error during controller refresh: %s" % e.error)


@synchronous
def refresh(system_id, consumer_key, token_key, token_secret, maas_url=None):
    """Run all builtin commissioning scripts and report results to region."""
    maaslog.info("Refreshing rack controller hardware information.")

    if maas_url is None:
        maas_url = "http://127.0.0.1:5240/MAAS"
    url = "%s/metadata/%s/" % (maas_url, MD_VERSION)

    creds = {
        "consumer_key": consumer_key,
        "token_key": token_key,
        "token_secret": token_secret,
        "consumer_secret": "",
    }

    scripts = {
        name: config
        for name, config in NODE_INFO_SCRIPTS.items()
        if config["run_on_controller"]
    }

    with tempfile.TemporaryDirectory(prefix="maas-commission-") as tmpdir:
        failed_scripts = runscripts(scripts, url, creds, tmpdir=tmpdir)

    if len(failed_scripts) == 0:
        signal_wrapper(url, creds, "OK", "Finished refreshing %s" % system_id)
    else:
        signal_wrapper(
            url, creds, "FAILED", "Failed refreshing %s" % system_id
        )


def runscripts(scripts, url, creds, tmpdir):
    total_scripts = len(scripts)
    current_script = 1
    failed_scripts = []
    out_dir = os.path.join(tmpdir, "out")
    os.makedirs(out_dir)
    for script_name in sorted(scripts.keys()):
        signal_wrapper(
            url,
            creds,
            "WORKING",
            "Starting %s [%d/%d]"
            % (script_name, current_script, total_scripts),
        )

        if script_name == LXD_OUTPUT_NAME:
            # Execute the LXD binary directly as we are already on the
            # rack controller and don't need to download it.
            if running_in_snap():
                script_path = os.path.join(
                    get_snap_path(),
                    "usr/share/maas/machine-resources",
                    get_architecture().split("/")[0],
                )
            else:
                script_path = os.path.join(
                    "/usr/share/maas/machine-resources",
                    get_architecture().split("/")[0],
                )
        else:
            script_path = os.path.join(os.path.dirname(__file__), script_name)

        combined_path = os.path.join(out_dir, script_name)
        stdout_name = "%s.out" % script_name
        stdout_path = os.path.join(out_dir, stdout_name)
        stderr_name = "%s.err" % script_name
        stderr_path = os.path.join(out_dir, stderr_name)
        result_name = "%s.yaml" % script_name
        result_path = os.path.join(out_dir, result_name)

        env = copy.deepcopy(os.environ)
        env["OUTPUT_COMBINED_PATH"] = combined_path
        env["OUTPUT_STDOUT_PATH"] = stdout_path
        env["OUTPUT_STDERR_PATH"] = stderr_path
        env["RESULT_PATH"] = result_path

        timeout = 60

        try:
            proc = Popen(
                script_path, stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env=env
            )
            capture_script_output(
                proc, combined_path, stdout_path, stderr_path, timeout
            )
        except OSError as e:
            if isinstance(e.errno, int) and e.errno != 0:
                exit_status = e.errno
            else:
                # 2 is the return code bash gives when it can't execute.
                exit_status = 2
            result = str(e).encode()
            if result == b"":
                result = b"Unable to execute script"
            files = {script_name: result, stderr_name: result}
            signal_wrapper(
                url,
                creds,
                "WORKING",
                files=files,
                exit_status=exit_status,
                error="Failed to execute %s [%d/%d]: %d"
                % (script_name, current_script, total_scripts, exit_status),
            )
            failed_scripts.append(script_name)
        except TimeoutExpired:
            files = {
                script_name: open(combined_path, "rb").read(),
                stdout_name: open(stdout_path, "rb").read(),
                stderr_name: open(stderr_path, "rb").read(),
            }
            signal_wrapper(
                url,
                creds,
                "TIMEDOUT",
                files=files,
                error="Timeout(%s) expired on %s [%d/%d]"
                % (str(timeout), script_name, current_script, total_scripts),
            )
            failed_scripts.append(script_name)
        else:
            files = {
                script_name: open(combined_path, "rb").read(),
                stdout_name: open(stdout_path, "rb").read(),
                stderr_name: open(stderr_path, "rb").read(),
            }
            if os.path.exists(result_path):
                files[result_name] = open(result_path, "rb").read()
            signal_wrapper(
                url,
                creds,
                "WORKING",
                files=files,
                exit_status=proc.returncode,
                error="Finished %s [%d/%d]: %d"
                % (
                    script_name,
                    current_script,
                    total_scripts,
                    proc.returncode,
                ),
            )
            if proc.returncode != 0:
                failed_scripts.append(script_name)

        current_script += 1

    return failed_scripts
