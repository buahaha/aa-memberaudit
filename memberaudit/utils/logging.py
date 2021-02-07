import logging


###################
# logging


class LoggerAddTag(logging.LoggerAdapter):
    """add custom tag to a logger"""

    def __init__(self, my_logger, prefix):
        super(LoggerAddTag, self).__init__(my_logger, {})
        self.prefix = prefix

    def process(self, msg, kwargs):
        return "[%s] %s" % (self.prefix, msg), kwargs


logger = LoggerAddTag(logging.getLogger(__name__), __package__)


def make_logger_prefix(tag: str):
    """creates a function to add logger prefix, which returns tag when used empty"""
    return lambda text="": "{}{}".format(tag, (": " + text) if text else "")
