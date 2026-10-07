#!/usr/bin/env python3
"""Build the standalone HTML model and block pages using only the standard library."""
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def render_content(block, combined=False):
    number = block['number']
    prefix = f'b{number}-' if combined else ''
    heading = 3 if combined else 2
    toc = [f'<p class="nav-group">Содержание блока</p><a href="#{prefix}overview">Обзор компетенций</a>']
    cards, sections = [], []
    for index, competency in enumerate(block['competencies'], 1):
        code = f'{number}.{index}'
        sid = prefix + competency['id']
        toc.append(f'<a class="nav-main" href="#{sid}">{code}. {escape(competency["short"])}</a>')
        for suffix, label in [('knows', 'Что знает'), ('skills', 'Что умеет'), ('example', 'Пример поведения')]:
            toc.append(f'<a class="nav-l2" href="#{sid}-{suffix}">{label}</a>')
        cards.append(f'<a class="overview-card" href="#{sid}"><span class="code">{code}</span><strong>{escape(competency["question"])}</strong><span class="question">{escape(competency["caption"])}</span></a>')
        section = [f'<section id="{sid}" aria-labelledby="{sid}-title"><div class="section-heading"><span class="number" aria-hidden="true">{code}</span><div><p class="section-label">Компетенция {code}</p><h{heading} id="{sid}-title">{escape(competency["title"])}</h{heading}></div></div><div class="columns">']
        for css, key, label in [('knowledge', 'knows', 'Что знает'), ('skills', 'skills', 'Что умеет')]:
            section.append(f'<div class="{css}" id="{sid}-{key}"><h{heading+1}>{label}</h{heading+1}><ul>')
            section.extend(f'<li>{escape(item)}</li>' for item in competency[key])
            section.append('</ul></div>')
        section.append(f'</div><div class="example" id="{sid}-example"><h{heading+1}>Пример корректного управленческого поведения</h{heading+1}><p>{escape(competency["example"])}</p></div></section>')
        sections.append('\n'.join(section))
    overview = f'<section class="overview" id="{prefix}overview" aria-labelledby="{prefix}overview-title"><h{heading} id="{prefix}overview-title">{escape(block["overview_title"])}</h{heading}><p>{escape(block["overview_text"])}</p><div class="overview-grid">' + ''.join(cards) + '</div></section>'
    if block['sources']:
        toc.append(f'<a class="nav-main" href="#{prefix}references">Методические ориентиры</a>')
        refs = f'<section class="reference-section" id="{prefix}references" aria-labelledby="{prefix}references-title"><h{heading} id="{prefix}references-title">Методические ориентиры</h{heading}><ul>'
        for source in block['sources']:
            refs += f'<li><a href="{escape(source["url"], quote=True)}">{escape(source["title"])}</a> — {escape(source["note"])}</li>'
        sections.append(refs + '</ul></section>')
    toc.append(f'<p class="nav-note">{escape(block["flow"])}</p>')
    return '\n'.join(toc), overview + '\n' + '\n'.join(sections)


def metadata(block):
    return f'<p class="sub">Блок {block["number"]} · Знания, умения и примеры управленческого поведения</p><div class="meta"><span class="badge badge-blue">{len(block["competencies"])} компетенции</span><span class="badge badge-{block["status_class"]}">{escape(block["status"])}</span><span class="badge badge-muted">{escape(block["date"])}</span></div><p class="intro">{escape(block["intro"])}</p>'


def head(title, description, css):
    return f'''<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="description" content="{escape(description, quote=True)}">
<meta name="theme-color" content="#f5f6f8">
<title>{escape(title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;500;600;700&amp;display=swap" rel="stylesheet">
<style>{css}</style></head><body>
<a class="skip" href="#content">Перейти к содержанию</a>
'''


def build():
    model = json.loads((ROOT / 'model-content.json').read_text())
    blocks = model['blocks']
    assert [b['number'] for b in blocks] == list(range(1, 9))
    assert all(len(b['competencies']) == 3 for b in blocks)
    templates = {name: (ROOT / 'templates' / name).read_text() for name in ['block.css', 'block.js', 'model.css', 'model.js']}
    extra_css = '''
.reference-section li{font-size:10px;color:var(--muted);line-height:1.55}
.reference-section a{font-weight:600;text-underline-offset:2px}
.model-scope{margin-top:7px;font-size:10px;color:var(--muted);max-width:110ch}
.model-status{margin-top:4px;font-size:9.5px;color:var(--muted)}
.section-heading>div{min-width:0}
@media(max-width:480px){.hero-top{flex-wrap:wrap}.block-header .block-title{overflow-wrap:anywhere}}
@media print{
 .block-content .columns li,.block-content .example p{line-height:1.4}
 .model-footer{position:fixed;left:0;right:0;bottom:-9mm;margin:0;font-size:8px}
 .reference-section{break-inside:avoid;page-break-inside:avoid}
 .block-content .reference-section{padding:6px 10px}
 .block-content .reference-section h3{font-size:10px;margin-bottom:4px}
 .block-content .reference-section ul{margin:0;padding-left:12px}
 .block-content .reference-section li{font-size:8.5px;line-height:1.3;margin-bottom:2px}
 .reference-section li{break-inside:avoid}
}
'''
    panels, tabs = [], []
    for block in blocks:
        number = block['number']
        toc, content = render_content(block)
        page = head(f'{block["title"]} · Блок {number}', block['intro'], templates['block.css'] + extra_css)
        page += f'<div class="page" id="top"><header><div class="hero-top"><p class="eyebrow">Модель компетенций управленца в здравоохранении</p><button class="print" type="button" onclick="window.print()">Печать / PDF</button></div><h1>{escape(block["title"])}</h1>{metadata(block)}</header><nav aria-label="Оглавление блока {number}">{toc}</nav><main id="content">{content}</main>'
        footer_links = [f'<a href="competency-model.html#block-{number}">Общая модель</a>']
        if number > 1:
            footer_links.append(f'<a href="block-{number-1}-competencies.html">← Блок {number-1}</a>')
        if number < len(blocks):
            footer_links.append(f'<a href="block-{number+1}-competencies.html">Блок {number+1} →</a>')
        footer_links.append('<a href="#top">К началу ↑</a>')
        page += f'<footer><span>Модель компетенций · Блок {number} · {escape(block["date"])}</span>{"".join(footer_links)}</footer></div><script>{templates["block.js"]}</script></body></html>\n'
        (ROOT / f'block-{number}-competencies.html').write_text(page)
        toc, content = render_content(block, combined=True)
        panels.append(f'<article class="block-panel" id="block-{number}" aria-labelledby="b{number}-block-{number}-title"><div class="block-layout"><header class="block-header"><h2 id="b{number}-block-{number}-title" class="block-title">{escape(block["title"])}</h2>{metadata(block)}</header><nav class="block-toc" aria-label="Оглавление блока {number}">{toc}</nav><div class="block-content">{content}</div></div></article>')
        tabs.append(f'<a class="block-tab" href="#block-{number}" aria-controls="block-{number}"><span class="tab-number">{number:02d}</span><span>{escape(block["title"])}</span></a>')
    page = head('Модель компетенций · 8 блоков · 24 компетенции', 'Модель компетенций управленца в здравоохранении: восемь блоков, знания, умения и примеры для разных уровней управления.', templates['model.css'] + extra_css)
    page += '<div class="page model-page" id="top"><header class="model-header"><div class="hero-top"><div><p class="eyebrow">Здравоохранение · 8 блоков · 24 компетенции</p><h1>Модель управленческих компетенций</h1></div><button class="print" type="button" onclick="window.print()">Печать всей модели / PDF</button></div><p class="model-scope">Для руководителей подразделений, медицинских организаций, сетей, регионов и системы здравоохранения. Масштаб решений определяется ответственностью и полномочиями руководителя.</p><p class="model-status">Блоки 1, 3 и 4 согласованы · Блок 2 пересмотрен с учётом уровней управления · Блоки 5–8 подготовлены для просмотра</p></header>'
    page += '<nav class="block-tabs" aria-label="Выбор блока">' + ''.join(tabs) + '</nav><main id="content">' + '\n'.join(panels) + '</main>'
    page += f'<footer class="model-footer"><span>Модель компетенций · 8 блоков · 24 компетенции · Редакция от {escape(model["edition"])}</span><a href="#top">К началу ↑</a></footer></div><script>{templates["model.js"]}</script></body></html>\n'
    (ROOT / 'competency-model.html').write_text(page)
    # A readable export for reviewing wording independently of the HTML layout.
    lines = ['# Модель управленческих компетенций в здравоохранении', '', f'Редакция: {model["edition"]}.', '', 'Исходные данные: `model-content.json`. Этот файл и HTML создаются командой `python3 tools/render_model.py`.', '']
    for block in blocks:
        lines += [f'## Блок {block["number"]}. {block["title"]}', '', f'Статус: {block["status"]}. Дата: {block["date"]}.', '', block['intro'], '']
        for i, competency in enumerate(block['competencies'], 1):
            lines += [f'### {block["number"]}.{i}. {competency["title"]}', '', '**Что знает**', '']
            lines += [f'- {item}' for item in competency['knows']]
            lines += ['', '**Что умеет**', '']
            lines += [f'- {item}' for item in competency['skills']]
            lines += ['', '**Пример поведения**', '', competency['example'], '']
        if block['sources']:
            lines += ['**Методические ориентиры**', '']
            lines += [f'- [{s["title"]}]({s["url"]}) — {s["note"]}' for s in block['sources']]
            lines.append('')
    (ROOT / 'model-content.md').write_text('\n'.join(lines))
    from render_report import build_report
    build_report(model, ROOT, render_content, metadata, head)
    print('Built full review report, model, 8 block pages and Markdown (24 competencies).')


if __name__ == '__main__':
    build()
