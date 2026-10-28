const assert = require("node:assert/strict");
const {test} = require("node:test");
const {execFileSync} = require("node:child_process");
const path = require("node:path");
const {JSDOM} = require("jsdom");

const root = path.resolve(__dirname, "../..");
const build = `
from src.contact_table import build_contact_table
from src.demo import demo_data
from src.prospecting import prepare_data, now_local
df = prepare_data(demo_data(now_local().date()))
df['idade_anos'] = 3.0
df['reviewed'] = [False, False, True, False]
df['cnpj'] = ['00000000000001', '00000000000002', '00000000000003', '00000000000004']
df.loc[0, 'razao_social'] = '<img src=x onerror="window.injected=true"> & Loja'
df.loc[1, 'whatsapp_2'] = '5500000000001'
df.loc[1, 'celular_1_provavel'] = False
df.loc[1, 'celular_2_provavel'] = True
df.loc[3, 'whatsapp_1'] = ''
print(build_contact_table(df, '{saudacao}, {nome}! 20% + café', 'Daniel & Sebrae', None, False, 'Claro'))
`;
const markup = execFileSync(process.env.PYTHON || "python", ["-c", build], {cwd: root, encoding: "utf8"});
function setup(options = {}) {
    const opened = [];
    const confirmed = [];
    const dom = new JSDOM(markup, {
        url: "https://app.example/component", referrer: "https://app.example/prospeccao/?old=1",
        runScripts: "dangerously", ...options,
        beforeParse(window) {
            window.contactTableOptions = {onMark: numbers => confirmed.push([...numbers])};
            window.open = (url, target) => {
                const tab = {opener: window, location: {replace: href => opened.push({href, url, target, tab})}};
                return tab;
            };
        }
    });
    const doc = dom.window.document;
    return {dom, doc, opened, confirmed, boxes: [...doc.querySelectorAll('.row-select')],
        click: id => doc.getElementById(id).click()};
}

test("select page, clear and checkbox header include only eligible companies", () => {
    const {dom, doc, boxes, click, opened} = setup();
    assert.deepEqual(boxes.map(b => b.disabled), [false, false, true, true]);
    boxes[0].click();
    assert.equal(doc.getElementById('select-all').indeterminate, true);
    assert.equal(doc.getElementById('selection-count').textContent, '1 empresa selecionada');
    click('select-page');
    assert.equal(boxes.filter(b => b.checked).length, 2);
    assert.equal(doc.getElementById('select-all').checked, true);
    click('clear-selection');
    assert.equal(boxes.filter(b => b.checked).length, 0);
    assert.equal(doc.getElementById('open-selected').disabled, true);
    click('select-all');
    assert.equal(boxes.filter(b => b.checked).length, 2);
    assert.equal(opened.length, 0);
    dom.window.close();
});

test("one click opens WhatsApp directly and keeps selection for explicit contact confirmation", () => {
    const {dom, doc, boxes, click, opened, confirmed} = setup();
    click('select-page');
    click('open-selected');
    assert.equal(opened.length, 2);
    const urls = opened.map(o => new URL(o.href));
    assert.ok(urls.every(u => u.origin === 'https://web.whatsapp.com' && u.pathname === '/send'));
    assert.equal(urls[1].searchParams.get('phone'), '5500000000001');
    assert.match(urls[0].searchParams.get('text'), /Maria! 20% \+ café$/);
    assert.equal(urls[0].searchParams.has('contact'), false);
    assert.equal(confirmed.length, 0);
    assert.ok(opened.every(o => o.target === '_blank' && o.tab.opener === null));
    assert.ok(boxes.slice(0, 2).every(b => !b.disabled && b.checked));
    assert.equal(doc.getElementById('open-selected').disabled, true);
    click('select-page');
    click('open-selected');
    assert.equal(opened.length, 2); // Não repete empresas já abertas.
    assert.match(doc.getElementById('batch-status').textContent, /2 aba\(s\) aberta/);
    click('mark-contacted');
    assert.deepEqual(confirmed, [['00000000000001', '00000000000002']]);
    dom.window.close();
});

test("blocked popups remain selected and retry opens only the remaining company", () => {
    const {dom, doc, boxes, click, opened} = setup();
    const realOpen = dom.window.open;
    let calls = 0;
    dom.window.open = (...args) => ++calls === 2 ? null : realOpen(...args);
    click('select-page');
    click('open-selected');
    assert.equal(opened.length, 1);
    assert.equal(boxes[0].dataset.opened, 'true');
    assert.equal(boxes[1].checked, true);
    assert.equal(boxes[1].disabled, false);
    assert.match(doc.getElementById('batch-status').textContent, /1 bloqueada/);
    dom.window.open = realOpen;
    click('open-selected');
    assert.equal(opened.length, 2);
    assert.equal(new URL(opened[1].href).searchParams.get('phone'), '5500000000001');
    dom.window.close();
});

test("total popup blocking does not clear selection or claim any opening", () => {
    const {dom, doc, boxes, click, opened} = setup();
    dom.window.open = () => null;
    click('select-page');
    click('open-selected');
    assert.equal(opened.length, 0);
    assert.equal(boxes.filter(b => b.checked).length, 2);
    assert.match(doc.getElementById('batch-status').textContent, /^0 aba/);
    dom.window.close();
});

test("company text is escaped and individual links already point directly at WhatsApp", () => {
    const {dom, doc} = setup();
    assert.equal(dom.window.injected, undefined);
    assert.equal(doc.querySelectorAll('img').length, 0);
    assert.match(doc.querySelector('.company').textContent, /<img src=x/);
    const links = [...doc.querySelectorAll('a')];
    assert.equal(links.length, 3);
    assert.ok(links.every(a => new URL(a.href).hostname === 'web.whatsapp.com'));
    dom.window.close();
});

test("batch works without a referrer because it does not depend on an app redirect", () => {
    const {dom, doc, boxes, click, opened} = setup({url: 'about:blank', referrer: undefined});
    click('select-page');
    click('open-selected');
    assert.equal(opened.length, 2);
    assert.ok(opened.every(o => new URL(o.href).hostname === 'web.whatsapp.com'));
    dom.window.close();
});

test("the Streamlit bridge reports explicit confirmations only and preserves state on rerender", () => {
    const fs = require('node:fs');
    const {dom, doc, click} = setup();
    const messages = [];
    dom.window.parent.postMessage = message => messages.push(message);
    const index = fs.readFileSync(path.join(root, 'src/contact_table_frontend/index.html'), 'utf8');
    const bridge = new JSDOM(index).window.document.querySelector('script:not([src])').textContent;
    dom.window.eval(bridge);
    const render = id => dom.window.dispatchEvent(new dom.window.MessageEvent('message', {
        source: dom.window.parent, data: {type: 'streamlit:render', args: {identity: id, markup, height: 800}}
    }));
    render('page-one');
    click('select-page');
    click('open-selected');
    render('page-one');
    assert.equal(doc.getElementById('open-selected').disabled, true);
    assert.equal(messages.filter(m => m.type === 'streamlit:setComponentValue').length, 0);
    click('mark-contacted');
    const value = messages.find(m => m.type === 'streamlit:setComponentValue');
    assert.equal(value.dataType, 'json');
    assert.equal(value.value.action, 'mark_contacted');
    assert.deepEqual([...value.value.cnpjs], ['00000000000001', '00000000000002']);
    render('page-two');
    assert.equal(doc.querySelectorAll('.row-select:checked').length, 0);
    dom.window.close();
});
