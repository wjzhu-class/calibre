#!/usr/bin/env python2
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import with_statement

__license__   = 'GPL v3'
__copyright__ = '2009, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import os, ast, json

from calibre.utils.config import config_dir, prefs, tweaks
from calibre.utils.lock import ExclusiveFile
from calibre import sanitize_file_name
from calibre.customize.conversion import OptionRecommendation
from calibre.customize.ui import available_output_formats


config_dir = os.path.join(config_dir, 'conversion')
if not os.path.exists(config_dir):
    os.makedirs(config_dir)


def name_to_path(name):
    return os.path.join(config_dir, sanitize_file_name(name)+'.py')


def save_defaults(name, recs):
    path = name_to_path(name)
    raw = recs.serialize()
    with lopen(path, 'wb'):
        pass
    with ExclusiveFile(path) as f:
        f.write(raw)


def load_defaults(name):
    path = name_to_path(name)
    if not os.path.exists(path):
        open(path, 'wb').close()
    with ExclusiveFile(path) as f:
        raw = f.read()
    r = GuiRecommendations()
    if raw:
        r.deserialize(raw)
    return r


def load_all_defaults():
    ans = {}
    for x in os.listdir(config_dir):
        if x.endswith('.py'):
            path = os.path.join(config_dir, x)
            with ExclusiveFile(path) as f:
                raw = f.read()
            r = GuiRecommendations()
            if raw:
                r.deserialize(raw)
            ans[os.path.splitext(x)[0]] = r.copy()
    return ans


def save_specifics(db, book_id, recs):
    raw = recs.serialize()
    db.set_conversion_options(book_id, 'PIPE', raw)


def load_specifics(db, book_id):
    raw = db.conversion_options(book_id, 'PIPE')
    r = GuiRecommendations()
    if raw:
        r.deserialize(raw)
    return r


def delete_specifics(db, book_id):
    db.delete_conversion_options(book_id, 'PIPE')


class GuiRecommendations(dict):

    def __new__(cls, *args):
        dict.__new__(cls)
        obj = super(GuiRecommendations, cls).__new__(cls, *args)
        obj.disabled_options = set([])
        return obj

    def to_recommendations(self, level=OptionRecommendation.LOW):
        ans = []
        for key, val in self.items():
            ans.append((key, val, level))
        return ans

    def __str__(self):
        ans = ['{']
        for key, val in self.items():
            ans.append('\t'+repr(key)+' : '+repr(val)+',')
        ans.append('}')
        return '\n'.join(ans)

    def serialize(self):
        ans = json.dumps(self, indent=2, ensure_ascii=False)
        if isinstance(ans, unicode):
            ans = ans.encode('utf-8')
        return b'json:' + ans

    def deserialize(self, raw):
        try:
            if raw.startswith(b'json:'):
                d = json.loads(raw[len(b'json:'):])
            else:
                d = ast.literal_eval(raw)
        except Exception:
            pass
        else:
            if d:
                self.update(d)
    from_string = deserialize

    def merge_recommendations(self, get_option, level, options,
            only_existing=False):
        for name in options:
            if only_existing and name not in self:
                continue
            opt = get_option(name)
            if opt is None:
                continue
            if opt.level == OptionRecommendation.HIGH:
                self[name] = opt.recommended_value
                self.disabled_options.add(name)
            elif opt.level > level or name not in self:
                self[name] = opt.recommended_value


def get_available_formats_for_book(db, book_id):
    available_formats = db.new_api.formats(book_id)
    return {x.lower() for x in available_formats}


class NoSupportedInputFormats(Exception):

    def __init__(self, available_formats):
        Exception.__init__(self)
        self.available_formats = available_formats


def get_supported_input_formats_for_book(db, book_id):
    from calibre.ebooks.conversion.plumber import supported_input_formats
    available_formats = get_available_formats_for_book(db, book_id)
    input_formats = {x.lower() for x in supported_input_formats()}
    input_formats = sorted(available_formats.intersection(input_formats))
    if not input_formats:
        raise NoSupportedInputFormats(tuple(x for x in available_formats if x))
    return input_formats


def get_preferred_input_format_for_book(db, book_id):
    recs = load_specifics(db, book_id)
    if recs:
        return recs.get('gui_preferred_input_format', None)


def sort_formats_by_preference(formats, prefs):
    uprefs = {x.upper():i for i, x in enumerate(prefs)}

    def key(x):
        return uprefs.get(x.upper(), len(prefs))

    return sorted(formats, key=key)


def get_input_format_for_book(db, book_id, pref=None):
    '''
    Return (preferred input format, list of available formats) for the book
    identified by book_id. Raises an error if the book has no input formats.

    :param pref: If None, the format used as input for the last conversion, if
    any, on this book is used. If not None, should be a lowercase format like
    'epub' or 'mobi'. If you do not want the last converted format to be used,
    set pref=False.
    '''
    if pref is None:
        pref = get_preferred_input_format_for_book(db, book_id)
    if hasattr(pref, 'lower'):
        pref = pref.lower()
    input_formats = get_supported_input_formats_for_book(db, book_id)
    input_format = pref if pref in input_formats else \
        sort_formats_by_preference(input_formats, prefs['input_format_order'])[0]
    return input_format, input_formats


def get_output_formats(preferred_output_format):
    all_formats = {x.upper() for x in available_output_formats()}
    all_formats.discard('OEB')
    pfo = preferred_output_format.upper() if preferred_output_format else ''
    restrict = tweaks['restrict_output_formats']
    if restrict:
        fmts = [x.upper() for x in restrict]
        if pfo and pfo not in fmts and pfo in all_formats:
            fmts.append(pfo)
    else:
        fmts = list(sorted(all_formats,
            key=lambda x:{'EPUB':'!A', 'AZW3':'!B', 'MOBI':'!C'}.get(x.upper(), x)))
    return fmts


def get_sorted_output_formats():
    preferred_output_format = prefs['output_format'].upper()
    fmts = get_output_formats(preferred_output_format)
    try:
        fmts.remove(preferred_output_format)
    except Exception:
        pass
    fmts.insert(0, preferred_output_format)
    return fmts
