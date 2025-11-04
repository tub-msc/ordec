# SPDX-FileCopyrightText: 2025 ORDeC contributors
# SPDX-License-Identifier: Apache-2.0

import shlex
import subprocess
import xml.etree.ElementTree as ET
import re
from dataclasses import dataclass

from ..core import *

def run(script, cwd, **kwargs):
    """
    Run KLayout script 'script' in directory 'cwd' with provieded keyword args.
    """
    cmdline = ['klayout', '-b', '-r', str(script)]
    for k, v in kwargs.items():
        cmdline += ['-rd', f'{k}={v}']
    #print(cwd, shlex.join(cmdline))
    subprocess.check_call(cmdline, cwd=cwd)

@dataclass
class DrcResult:
    category: 'DrcCategory'
    layout: Layout
    values: list[str]

@dataclass
class DrcCategory:
    name: str
    description: str
    results: list[DrcResult]

@dataclass
class DrcReport:
    categories: list[DrcCategory]

    def pretty(self):
        ret = []
        indent = '    '
        nresults = 0
        for category in self.categories:
            if len(category.results) == 0:
                continue
            nresults += len(category.results)
            ret.append(f"{category.name} ({len(category.results)} result{'s' if len(category.results)!=1 else ''}):")
            ret.append(f'{indent}{category.description}')
            for result in category.results:
                layout = result.layout
                if layout.cell is None:
                    layout_name = f"__{id(layout.subgraph):x}"
                else:
                    layout_name = repr(layout.cell)
                values = result.values
                if len(values) == 1:
                    ret.append(f'{indent}{layout_name}: {values[0]}')
                else:
                    ret.append(f'{indent}{layout_name}:')
                    for value in values:
                        ret.append(f'{2*indent}{value}')

            ret.append('')
        header = f"DRC Report ({nresults} results total)"
        ret.insert(0, header)
        ret.insert(1, '='*len(header))
        ret.insert(2, '')
        if nresults == 0:
            ret.append("No DRC results produced. :)")
        return '\n'.join(ret)

    def nresults(self):
        return sum([len(category.results) for category in self.categories])

    def summary(self):
        summary = {}
        for category in self.categories:
            if len(category.results) == 0:
                continue
            summary[category.name] = len(category.results)
        return summary


def parse_rdb(filename, name_of_layout) -> DrcReport:
    """
    Parses a KLayout XML result database file (RDB). At the moment, this is
    built for IHP130 DRC only.

    See also: https://www.klayout.de/rdb_format.html
    """
    out = DrcReport(categories=[])
    category_by_name = {}
    layout_of_name = {v: k for k, v in name_of_layout.items()}

    tree = ET.parse(filename)

    for category in tree.find('categories').iter('category'):
        name = category.find('name', '').text
        description = category.find('description', '').text
        category = DrcCategory(name=name, description=description, results=[])
        category_by_name[name] = category
        out.categories.append(category)

    for item in tree.find('items').iter('item'):
        category = item.find('category').text
        category = re.sub(r"(^')|('$)", "", category)
        category = category_by_name[category]
        layout = item.find('cell').text
        layout = layout_of_name[layout]
        values = [v.text for v in item.iter('value')]
        result = DrcResult(category=category, layout=layout, values=values)
        category.results.append(result)

    return out
