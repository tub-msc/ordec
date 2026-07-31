; SPDX-FileCopyrightText: 2016 Max Brunsfeld
; SPDX-FileCopyrightText: 2026 ORDeC contributors
; SPDX-License-Identifier: MIT AND Apache-2.0

; Helix variant of highlights.scm: the same rules in the same order (Helix
; 25.07+ resolves captures last-match-wins like Neovim), but with Helix
; theme scope names as captures. Helix styles captures by looking them up
; as theme scopes, and no Helix theme defines @property, @number or
; @escape. Those render unstyled and need @variable.other.member,
; @constant.numeric and @constant.character.escape instead. Keep rule
; content and order in sync with highlights.scm. The test suite compares
; the two files modulo capture names.

; Python-like identifier conventions (generic captures, refined below)

(identifier) @variable

((identifier) @type
 (#match? @type "^[A-Z]"))

((identifier) @constant
 (#match? @constant "^[A-Z][A-Z_]*$"))

; Attribute access comes before the call captures so method calls win over
; the generic member capture

(attribute
  attribute: (identifier) @variable.other.member)

; Functions, calls, decorators

(decorator) @function
(decorator
  (identifier) @function)

(function_definition
  name: (identifier) @function)

(call
  function: (attribute attribute: (identifier) @function.method))

(call
  function: (identifier) @function)

((call
  function: (identifier) @function.builtin)
 (#match?
   @function.builtin
   "^(abs|all|any|ascii|bin|bool|breakpoint|bytearray|bytes|callable|chr|classmethod|compile|complex|delattr|dict|dir|divmod|enumerate|eval|exec|filter|float|format|frozenset|getattr|globals|hasattr|hash|help|hex|id|input|int|isinstance|issubclass|iter|len|list|locals|map|max|memoryview|min|next|object|oct|open|ord|pow|print|property|range|repr|reversed|round|set|setattr|slice|sorted|staticmethod|str|sum|super|tuple|type|vars|zip|__import__)$"))

(type
  (identifier) @type)

; Literals

[
  (none)
  (true)
  (false)
] @constant.builtin

[
  (integer)
  (float)
] @constant.numeric

(comment) @comment
(string) @string
(escape_sequence) @constant.character.escape

(interpolation
  "{" @punctuation.special
  "}" @punctuation.special) @embedded

; Operators and keywords

[
  "--"
  "-"
  "-="
  "!"
  "!="
  "*"
  "**"
  "**="
  "*="
  "/"
  "//"
  "//="
  "/="
  "&"
  "&="
  "%"
  "%="
  "^"
  "^="
  "+"
  "->"
  "+="
  "<"
  "<<"
  "<<="
  "<="
  "<>"
  "="
  ":="
  "=="
  ">"
  ">="
  ">>"
  ">>="
  "|"
  "|="
  "~"
  "@="
  "and"
  "in"
  "is"
  "not"
  "or"
  "is not"
  "not in"
] @operator

[
  "as"
  "assert"
  "async"
  "await"
  "break"
  "class"
  "continue"
  "def"
  "del"
  "elif"
  "else"
  "except"
  "finally"
  "for"
  "from"
  "global"
  "if"
  "import"
  "lambda"
  "nonlocal"
  "pass"
  "raise"
  "return"
  "try"
  "while"
  "with"
  "yield"
  "match"
  "case"
] @keyword

; ORD declarations and headers (after the generic captures so they win)

[
  "cell"
  "viewgen"
  "path"
  "net"
  "anonymous"
] @keyword

(cell_definition
  name: (identifier) @type)

(viewgen_definition
  name: (identifier) @function)

(viewgen_definition
  return_type: (type (identifier) @type))

(viewgen_definition
  return_type: (type (attribute attribute: (identifier) @type)))

; Node statements: `output y:`, `Nmos n1:`, `Nmos(w=4u, l=400n) m1:`, `Net vdd`.

(node_statement
  kind: (identifier) @type)

(node_statement
  kind: (attribute
    attribute: (identifier) @type))

(node_statement
  kind: (call
    function: (identifier) @type))

(node_statement
  kind: (call
    function: (attribute
      attribute: (identifier) @type)))

(node_statement
  kind: (subscript value: (identifier) @type))

(node_statement
  kind: (subscript value: (attribute
    attribute: (identifier) @type)))

(node_statement
  target: (context_target (identifier) @variable))

(node_statement_nobody
  kind: (identifier) @type)

(node_statement_nobody
  kind: (attribute
    attribute: (identifier) @type))

(node_statement_nobody
  kind: (call
    function: (identifier) @type))

(node_statement_nobody
  kind: (call
    function: (attribute
      attribute: (identifier) @type)))

(node_statement_nobody
  kind: (subscript value: (identifier) @type))

(node_statement_nobody
  kind: (subscript value: (attribute
    attribute: (identifier) @type)))

(node_statement_nobody
  target: (context_target (identifier) @variable))

(path_net_statement
  name: (context_target (identifier) @variable))

; Directional pin kinds keep their traditional keyword look even though they
; are ordinary names in the grammar. Last of the kind captures so they beat
; the generic @type rules above.

((node_statement
  kind: (identifier) @keyword)
 (#any-of? @keyword "input" "output" "inout" "port"))

((node_statement_nobody
  kind: (identifier) @keyword)
 (#any-of? @keyword "input" "output" "inout" "port"))

; ORD member / parameter access, connections and constraints

; Two patterns: the attribute field is optional and the bare `.`
; (dotted_atom without a name) must still capture its dot.
(ord_local_attribute
  "." @punctuation.special)

(ord_local_attribute
  attribute: (identifier) @variable.other.member)

(ord_parameter_access
  "." @punctuation.special
  "$" @punctuation.special
  attribute: (identifier) @variable.other.member)

(ord_connection_statement
  "--" @operator)

(constrain_statement
  "!" @operator)
