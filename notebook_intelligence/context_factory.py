# Copyright (c) Mehmet Bektas <mbektasgh@outlook.com>

import os
from notebook_intelligence.ruleset import RuleContext


class RuleContextFactory:
    """Factory for creating RuleContext from various sources."""
    
    @staticmethod
    def create(
        filename: str,
        language: str,
        chat_mode_id: str,
        root_dir: str,
        kernel_name: str | None = None,
    ) -> RuleContext:
        """Create RuleContext from WebSocket message data."""
        return RuleContext(
            filename=filename,
            language=language,
            kernel_name=kernel_name or None,
            mode=chat_mode_id,
            directory=os.path.dirname(os.path.join(root_dir, filename))
        )
