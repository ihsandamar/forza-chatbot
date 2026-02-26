"""Report V2 Configuration."""
from src.graphs.report.configuration import ReportAgentConfiguration


class ReportV2Configuration(ReportAgentConfiguration):
    """
    Report V2 için runtime configuration.
    ReportAgentConfiguration'ı extend eder — tüm Text2SQL config field'ları miras alınır.
    V2'de enable_merged_text2sql her zaman True — override edilemez.
    """

    @property
    def enable_merged_text2sql(self) -> bool:
        return True
