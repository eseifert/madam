import collections
import subprocess

try:
    from subprocess import run as subprocess_run
except ImportError:
    _CompletedProcess = collections.namedtuple('_CompletedProcess', ['args', 'retcode', 'stdout', 'stderr'])


    def subprocess_run(command, stdin=None, input=None, check=False, stdout=None, stderr=None):
        if input is not None:
            if stdin is not None:
                raise ValueError('stdin and input arguments can not be used at the same time.')
            stdin = subprocess.PIPE

        with subprocess.Popen(command, stdin=stdin,
                              stdout=stdout, stderr=stderr) as process:
            try:
                stdout, stderr = process.communicate(input=input)
            except:
                process.kill()
                process.wait()
                raise
            retcode = process.poll()
            if check and retcode:
                raise subprocess.CalledProcessError(retcode, process.args,
                                                    output=stdout, stderr=stderr)
        return _CompletedProcess(args=process.args, retcode=retcode,
                                 stdout=stdout, stderr=stderr)
