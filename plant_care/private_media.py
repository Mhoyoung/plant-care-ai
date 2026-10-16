"""Keep personal attachments in the authenticated UI, outside shared /media URLs."""
from base64 import b64encode
from html import escape
import streamlit as st


def photo(data, width='stretch', personal=False):
    # Streamlit accepts image data URIs without registering a public media file.
    source = 'data:image/jpeg;base64,' + b64encode(data).decode('ascii') if personal else data
    st.image(source, width=width)


def download(store, label, data, *, file_name, mime, **options):
    if not getattr(store, 'personal', False):
        return st.download_button(label, data, file_name=file_name, mime=mime, **options)
    raw = data.encode('utf-8') if isinstance(data, str) else bytes(data)
    # srcdoc is sent over this authenticated Streamlit session. No unauthenticated
    # file URL or Supabase credential is created; logout removes the iframe.
    uri = f'data:{escape(mime, quote=True)};base64,' + b64encode(raw).decode('ascii')
    content = ('<!doctype html><html lang="ko"><meta charset="utf-8"><style>'
               'body{margin:0;font:14px Arial,sans-serif}a{box-sizing:border-box;display:flex;'
               'justify-content:center;align-items:center;min-height:46px;border:1px solid #d2d8ce;'
               'border-radius:10px;color:#254c35;background:#fff;text-decoration:none;padding:10px;}'
               'a:hover{background:#edf3e7}a:focus-visible{outline:2px solid #2e7d32;outline-offset:-3px}'
               '</style><a download="' + escape(file_name, quote=True) + '" href="' + uri + '" title="' +
               escape(str(options.get('help') or ''), quote=True) + '">' + escape(label) + '</a></html>')
    st.iframe(content, height=56, alt=label)
