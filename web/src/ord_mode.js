// SPDX-FileCopyrightText: 2025 ORDeC contributors
// SPDX-License-Identifier: Apache-2.0

import ace from "ace-builds/src-noconflict/ace";
import "ace-builds/src-noconflict/mode-python";

const PythonMode = ace.require("ace/mode/python").Mode;
const PythonHighlightRules = ace.require("ace/mode/python_highlight_rules").PythonHighlightRules;

class OrdHighlightRules extends PythonHighlightRules {
    constructor() {
        super();
        this.version = 1;
        this.$rules.start.unshift(
        	{
        		token: "keyword.control.ord",
                regex: "\\b(cell|gendef)\\b"
        	},
            {
                token: "keyword.definition.ord",
                regex: "\\b(inout|input|output|port|net|path)\\b"
            },
            { 
            	token: "keyword.operator.ord", 
            	regex: "--" 
            },
		    { 
		        token: ["punctuation.dot.ord", "keyword.operator.ord", "variable.ord"],
		        regex: "(\\.+)(\\$?)([A-Za-z_]\\w*)"
		    },
		    {
		        token: "constant.numeric.rational.ord",
		        regex: "\\b\\d+\\s*/\\s*\\d+\\b"
		    },
		    {
		        token: "constant.numeric.float.ord",
		        regex: "\\b(?:\\d+\\.\\d+|\\.\\d+)[afpnumkMGT]?\\b"
		    },
		    {
		        token: "constant.numeric.integer.ord",
		        regex: "\\b\\d+[afpnumkMGT]?\\b"
		    }
        );
    }
}

class OrdMode extends PythonMode {
    constructor() {
        super();
        this.HighlightRules = OrdHighlightRules;
    }
}

export { OrdMode };
