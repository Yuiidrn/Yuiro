import logging
from yuiro.logger import StatusPollFilter


def test_only_successful_status_poll_is_hidden():
    gate = StatusPollFilter()
    def record(path, status=200, method='GET'):
        return logging.LogRecord('uvicorn.access', 20, '', 0, '%s %s %s %s %s',
                                 ('local', method, path, '1.1', status), None)
    assert not gate.filter(record('/api/status'))
    assert not gate.filter(record('/api/status?poll=1'))
    assert gate.filter(record('/api/status', 500))
    assert gate.filter(record('/api/status', 401))
    assert gate.filter(record('/api/status', method='POST'))
    assert gate.filter(record('/api/diary'))
