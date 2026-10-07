"""Render the full sequential review report from the shared model content."""
from html import escape


def build_report(model, root, render_content, metadata, head):
    blocks = model['blocks']
    css = (root / 'templates/block.css').read_text() + (root / 'templates/report.css').read_text()
    script = (root / 'templates/report.js').read_text()
    toc = ['<p class="nav-group">Общий обзор</p><a href="#model-map">Карта модели</a><a href="#scope">Как применять модель</a>']
    rows, articles = [], []
    for block in blocks:
        n = block['number']
        toc.append(f'<a class="nav-main" href="#block-{n}">{n}. {escape(block["title"])}</a>')
        links = []
        for i, c in enumerate(block['competencies'], 1):
            sid = f'b{n}-{c["id"]}'
            toc.append(f'<a class="nav-l2" href="#{sid}">{n}.{i}. {escape(c["short"])}</a>')
            links.append(f'<a class="map-competency" href="#{sid}">{n}.{i}. {escape(c["title"])}</a>')
        rows.append(f'<tr><td><a href="#block-{n}"><strong>{n}. {escape(block["title"])}</strong></a></td><td>{"".join(links)}</td></tr>')
        _, content = render_content(block, combined=True)
        articles.append(f'<article class="report-block" id="block-{n}" aria-labelledby="b{n}-block-{n}-title"><header class="block-header"><h2 class="block-title" id="b{n}-block-{n}-title">{n}. {escape(block["title"])}</h2>{metadata(block)}</header>{content}</article>')
    toc.append('<p class="nav-group">Связи между блоками</p><a href="#boundaries">Границы и взаимосвязи</a>')
    intro = '''<section id="model-map" aria-labelledby="model-map-title"><h2 id="model-map-title">Карта модели: 8 блоков и 24 компетенции</h2><p>В каждой компетенции описаны необходимые знания, практические умения и пример корректного управленческого поведения. Ссылки в таблице ведут к полному описанию.</p><div class="tablewrap"><table><thead><tr><th scope="col">Блок</th><th scope="col">Компетенции</th></tr></thead><tbody>''' + ''.join(rows) + '</tbody></table></div></section>'
    intro += '''<section id="scope" aria-labelledby="scope-title"><h2 id="scope-title">Как применять модель</h2><p>Общая компетенция применяется в масштабе полномочий и ответственности руководителя. Конкретные примеры иллюстрируют возможные ситуации; они не ограничивают компетенцию указанной должностью.</p><div class="tablewrap"><table><thead><tr><th scope="col">Уровень ответственности</th><th scope="col">Масштаб применения</th></tr></thead><tbody><tr><td>Подразделение</td><td>Команда, смена, служба, локальные решения и взаимодействие со смежными участниками.</td></tr><tr><td>Медицинская организация</td><td>Согласование подразделений, распределение ресурсов, развитие организации и результаты помощи.</td></tr><tr><td>Сеть и регион</td><td>Взаимодействие организаций, территориальные различия, региональные программы и доступность помощи.</td></tr><tr><td>Системный и федеральный уровень</td><td>Общие правила, программы, механизмы обеспечения и оценка последствий решений для регионов и участников системы.</td></tr></tbody></table></div><p class="scope-note">Масштаб ответственности и степень владения компетенцией — разные характеристики. Эта редакция описывает содержание компетенций; шкалы оценки и проходные баллы в неё не включены.</p></section>'''
    boundaries = [
        ('1 и 2', 'Блок 1 — полномочия, основания и установленный порядок решений. Блок 2 — выбор целей, приоритетов и способов достижения результата.'),
        ('2 и 3', 'Блок 2 — стратегические цели и управление результатом. Блок 3 — процессная модель, AS IS, причины дефектов, TO BE и закрепление улучшений.'),
        ('3 и 4', 'Блок 3 — методы описания и совершенствования процессов. Блок 4 — качество помощи, предупреждение вреда и пациентский опыт как предмет управления.'),
        ('2 и 5', 'Блок 2 — выбор направлений развития. Блок 5 — расчёт потребности, распределение ресурсов, финансовое обоснование и устойчивость исполнения.'),
        ('5 и 6', 'Блок 5 — потребность в кадрах и обеспечение деятельности. Блок 6 — формирование команды, делегирование, развитие, мотивация и рабочая среда.'),
        ('6 и 7', 'Блок 6 — руководство командой и отношения в ней. Блок 7 — ясность коммуникации, переговоры и согласование интересов разных участников.'),
        ('4 и 7', 'Блок 4 — потребности и опыт пациента при организации помощи. Блок 7 — общение, вовлечение и объяснение решений различным аудиториям.'),
        ('5 и 8', 'Блок 5 — непрерывность деятельности при ресурсных сбоях. Блок 8 — качество данных, полезность цифровых решений и информационная безопасность.'),
    ]
    boundary_rows = ''.join(f'<tr><td>{label}</td><td>{escape(text)}</td></tr>' for label, text in boundaries)
    ending = '<section id="boundaries" aria-labelledby="boundaries-title"><h2 id="boundaries-title">Границы и взаимосвязи блоков</h2><p>Одна управленческая ситуация может требовать нескольких компетенций. В модели они разделены по предмету решения и наблюдаемым действиям руководителя.</p><div class="tablewrap"><table><thead><tr><th scope="col">Блоки</th><th scope="col">Различие содержания</th></tr></thead><tbody>' + boundary_rows + '</tbody></table></div><p class="scope-note">Методические источники приведены рядом с соответствующими блоками. Формулировки компетенций и примеры подготовлены для этой модели.</p></section>'
    page = head('Модель управленческих компетенций — полный отчёт', 'Полная редакция модели: 8 блоков, 24 компетенции, знания, умения и примеры управленческого поведения.', css)
    page += f'''<div class="page report-page" id="top"><header class="report-header"><div class="hero-top"><p class="eyebrow">Здравоохранение · Модель управленческих компетенций</p><button class="print" type="button" onclick="window.print()">Печать / PDF</button></div><h1>Модель управленческих компетенций в здравоохранении</h1><p class="sub">Полная редакция для общего просмотра · {escape(model['edition'])}</p><div class="meta"><span class="badge badge-blue">8 блоков</span><span class="badge badge-blue">24 компетенции</span><span class="badge badge-ok">Все блоки подготовлены</span></div><p class="intro">Весь материал собран последовательно в одном документе. Начните с карты модели или выберите нужный блок в оглавлении. Для каждой компетенции представлены знания, умения и пример поведения.</p><p class="report-status">Содержание блоков 1, 3 и 4 согласовано ранее. Блок 2 пересмотрен с учётом разных уровней управления; блоки 5–8 доработаны для общего просмотра.</p></header><nav class="report-toc" aria-label="Оглавление полного отчёта">{''.join(toc)}</nav><main class="report-content" id="content">{intro}{''.join(articles)}{ending}</main><footer class="report-footer"><span>Модель компетенций · Полная редакция · {escape(model['edition'])}</span><a href="#top">К началу ↑</a></footer></div><script>{script}</script></body></html>'''
    (root / 'competency-model-report.html').write_text(page + '\n')
