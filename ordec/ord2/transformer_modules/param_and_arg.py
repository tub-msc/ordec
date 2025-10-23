# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

# standard imports
from lark import Transformer
import ast

class ParamArgTransformer(Transformer):

    def parameters(self, nodes):
        """
        Parameters transformer that handles:
          - normal params
          - starparams: nested or flat form:
               - ("starparam", ast.arg)
               - (("starparam", ast.arg), poststar)
          - starguard
          - kwparams: ("kwparam", ast.arg)
        """

        posonlyargs, args = [], []
        vararg = None
        kwonlyargs, kw_defaults = [], []
        kwarg = None
        defaults = []

        # Ensures always return ast.arg instances
        def ensure_arg(node):
            if isinstance(node, ast.arg):
                return node
            if isinstance(node, str):
                return ast.arg(arg=node, annotation=None)

        def unpack_param(param, target_list, default_list=None):
            # p is "ast.arg" or ("arg_with_default", ast.arg, default_expr)
            if isinstance(param, tuple) and param[0] == "arg_with_default":
                target_list.append(ensure_arg(param[1]))
                if default_list is not None:
                    default_list.append(param[2])
            else:
                target_list.append(ensure_arg(param))
                if default_list is not None:
                    default_list.append(None)

        normal_params = []
        starparams = None
        kwparams = None

        # recognize normal params, starparams, kwparams
        for node in nodes:
            if isinstance(node, tuple):
                # ("kwparam", typedparam)
                if node[0] == "kwparam":
                    kwparams = node
                # ("starparam", typedparam)  or  ("starguard", ...)  (flat)
                elif node[0] in ("starparam", "starguard"):
                    starparams = node
                # (("starparam", typedparam), poststarparams) (nested)
                elif isinstance(node[0], tuple) and node[0][0] in ("starparam", "starguard"):
                    starparams = node
                else:
                    normal_params.append(node)
            else:
                normal_params.append(node)

        # Split in args and pos_args
        slash_index = normal_params.index("/") if "/" in normal_params else -1
        if slash_index != -1:
            params_pos = normal_params[:slash_index]
            params_args = normal_params[slash_index + 1:]
        else:
            params_pos = []
            params_args = normal_params[:]
        for param in params_pos:
            unpack_param(param, posonlyargs, defaults)
        for param in params_args:
            unpack_param(param, args, defaults)

        # process starparams if present
        if starparams:
            # (param_type, typedparam_or_None, poststar=(paramvalues, kwparams))
            param_type = None
            typed = None
            post = ([], None)

            # flat shape: ("starparam", typedparam) or ("starguard", something)
            if starparams[0] in ("starparam", "starguard"):
                param_type = starparams[0]
                #  (star, poststar)
                if len(starparams) > 1:
                    # ("starparam", typedparam)
                    typed = starparams[1] if param_type == "starparam" else None
                    if (isinstance(starparams[1], tuple) and len(starparams) == 2 and
                            isinstance(starparams[1][0], list)):
                        post = starparams[1]
            elif isinstance(starparams[0], tuple) and starparams[0][0] in ("starparam", "starguard"):
                inner = starparams[0]
                param_type = inner[0]
                typed = inner[1] if len(inner) > 1 else None
                if len(starparams) > 1:
                    post = starparams[1]

            if param_type == "starparam":
                vararg = ensure_arg(typed)
            else:
                vararg = None

            # post is expected to be (paramvalues, kwparams)
            if post:
                paramvalues, maybe_kwparam = post
                for paramvalue in paramvalues:
                    unpack_param(paramvalue, kwonlyargs, kw_defaults)
                if maybe_kwparam:
                    # maybe_kwparam is ("kwparam", typedparam)
                    kwarg = ensure_arg(maybe_kwparam[1])

        # if kwparams standalone set kwarg
        if kwparams:
            kwarg = ensure_arg(kwparams[1])

        if defaults:
            # drop leading Nones so defaults align with the last args
            while defaults and defaults[0] is None:
                defaults.pop(0)

        return ast.arguments(
            posonlyargs=posonlyargs,
            args=args,
            vararg=vararg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=defaults
        )

    def kwparams(self, nodes):
        typedparam = nodes[0]
        return "kwparam", typedparam

    def poststarparams(self, nodes):
        if len(nodes) == 0:
            return [], None

        kwparams = nodes[-1] if (
                isinstance(nodes[-1], tuple) and nodes[-1][0] == "kwparam"
        ) else None
        paramvalues = nodes[:-1] if kwparams else nodes
        return paramvalues, kwparams

    def starguard(self, nodes):
        return "starguard"

    def starparam(self, nodes):
        typedparam = nodes[0]
        return "starparam", typedparam

    def starparams(self, nodes):
        star = nodes[0]
        poststarparams = nodes[1] if len(nodes) > 1 else ([], None)
        return star, poststarparams

    def paramvalue(self, nodes):
        typedparam = nodes[0]
        default = nodes[1] if len(nodes) > 1 else None
        return "arg_with_default", typedparam, default

    def typedparam(self, nodes):
        # x:Int
        name = nodes[0]
        annotation = nodes[1] if len(nodes) > 1 else None
        return ast.arg(arg=name, annotation=annotation)

    def argvalue(self, nodes):
        arg_node = nodes[0]
        default = nodes[1] if len(nodes) == 2 else None
        return "argvalue", arg_node, default

    def stararg(self, nodes):
        argument = nodes[0]
        return "stararg", argument

    def kwargs(self, nodes):
        test = nodes[0]
        argvalues = nodes[1:] if len(nodes) > 1 else []
        return "kwargs", test, argvalues

    def starargs(self, nodes):
        return nodes

    def lambda_paramvalue(self, nodes):
        name_node = nodes[0]
        default_node = nodes[1] if len(nodes) > 1 else None
        arg_node = ast.arg(arg=name_node,
                           annotation=None)
        return arg_node, default_node

    def lambda_starparams(self, nodes):
        # parameters with leading stars
        vararg = None
        kwonlyargs = []
        kw_defaults = []
        kwarg = None

        index = 0
        if len(nodes) > 0 and isinstance(nodes[0], str):
            vararg = ast.arg(arg=nodes[0], annotation=None)
            index = 1

        while index < len(nodes):
            node = nodes[index]
            if isinstance(node, tuple) and isinstance(node[0], ast.arg):
                kwonlyargs.append(node[0])
                kw_defaults.append(node[1])
            elif isinstance(node, dict) and "kwarg" in node:
                kwarg = node["kwarg"]
            index += 1

        return ast.arguments(
            posonlyargs=[], args=[],
            vararg=vararg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=[]
        )

    def lambda_kwparams(self, nodes):
        argument = nodes[0]
        # return kwparams dict
        return {"kwarg": ast.arg(arg=argument, annotation=None)}

    def lambda_params(self, nodes):
        args = []
        defaults = []
        vararg = None
        kwonlyargs = []
        kw_defaults = []
        kwarg = None

        # construct the parameters
        for node in nodes:
            if isinstance(node, tuple) and isinstance(node[0], ast.arg):
                # lambda_paramvalue with optional default
                args.append(node[0])
                defaults.append(node[1])
            elif isinstance(node, str):
                # name -> positional arg, no default
                args.append(ast.arg(arg=node, annotation=None))
            elif isinstance(node, ast.arguments):
                if node.vararg:
                    vararg = node.vararg
                if node.kwarg:
                    kwarg = node.kwarg
                kwonlyargs.extend(node.kwonlyargs)
                kw_defaults.extend(node.kw_defaults)
            elif isinstance(node, dict) and "kwarg" in node:
                kwarg = node["kwarg"]

        return ast.arguments(
            posonlyargs=[],
            args=args,
            vararg=vararg,
            kwonlyargs=kwonlyargs,
            kw_defaults=kw_defaults,
            kwarg=kwarg,
            defaults=defaults
        )

    def lambdef(self, nodes):
        # lambda x, y=2, *args, **kw: x + y
        if len(nodes) == 2:
            params, body = nodes
        else:
            # set empty arguments for the lambda
            params = ast.arguments(
                posonlyargs=[], args=[], vararg=None,
                kwonlyargs=[], kw_defaults=[],
                kwarg=None, defaults=[]
            )
            body = nodes[0]

        return ast.Lambda(args=params, body=body)

    starargs_part = lambda self, nodes: nodes