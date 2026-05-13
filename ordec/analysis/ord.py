# SPDX-FileCopyrightText: 2026 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# Compatibility facade for callers that import from ordec.analysis.ord.
from .model import AnalysisDiagnostic
from .model import AnalysisImport
from .model import AnalysisPosition
from .model import AnalysisRange
from .model import AnalysisSymbol
from .model import DocumentAnalysis
from .model import position_before
from .model import position_before_or_equal
from .model import range_contains
from .parser_pass import analyze_ord
from .session import AnalysisSession
