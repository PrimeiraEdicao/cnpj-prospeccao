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
    const dom = new JSDOM(markup, {
        url: "https://app.example/component", referrer: "https://app.example/prospeccao/?old=1",
        runScripts: "dangerously", ...options,
        beforeParse(window) {
            window.open = (url, target) => {
                const tab = {opener: window, location: {replace: href => opened.push({href, url, target, tab})}};
                return tab;
            };
        }
    });
    const doc = dom.window.document;
    return {dom, doc, opened, boxes: [...doc.querySelectorAll('.row-select')],
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

test("one click opens a distinct tab per selected company via the validated app route", () => {
    const {dom, doc, boxes, click, opened} = setup();
    click('select-page');
    click('open-selected');
    assert.equal(opened.length, 2);
    const urls = opened.map(o => new URL(o.href));
    assert.deepEqual(urls.map(u => u.pathname), ['/prospeccao/', '/prospeccao/']);
    assert.deepEqual(urls.map(u => u.searchParams.get('contact')), ['00000000000001', '00000000000002']);
    assert.equal(urls[1].searchParams.get('phone'), '5500000000001');
    assert.equal(urls[0].searchParams.get('template'), '{saudacao}, {nome}! 20% + café');
    assert.equal(urls[0].searchParams.get('sender'), 'Daniel & Sebrae');
    assert.equal(new Set(urls.map(u => u.searchParams.get('attempt'))).size, 2);
    assert.ok(opened.every(o => o.target === '_blank' && o.tab.opener === null));
    assert.ok(boxes.every(b => b.disabled && !b.checked));
    click('select-page');
    click('open-selected');
    assert.equal(opened.length, 2); // Não repete empresas já abertas.
    assert.match(doc.getElementById('batch-status').textContent, /2 aba\(s\) aberta/);
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
    assert.equal(boxes[0].disabled, true);
    assert.equal(boxes[1].checked, true);
    assert.equal(boxes[1].disabled, false);
    assert.match(doc.getElementById('batch-status').textContent, /1 contato\(s\) continuam selecionados/);
    dom.window.open = realOpen;
    click('open-selected');
    assert.equal(opened.length, 2);
    assert.equal(new URL(opened[1].href).searchParams.get('contact'), '00000000000002');
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

test("company text is escaped and every individual link resolves outside the iframe", () => {
    const {dom, doc} = setup();
    assert.equal(dom.window.injected, undefined);
    assert.equal(doc.querySelectorAll('img').length, 0);
    assert.match(doc.querySelector('.company').textContent, /<img src=x/);
    const links = [...doc.querySelectorAll('a')];
    assert.equal(links.length, 3);
    assert.ok(links.every(a => new URL(a.href).pathname === '/prospeccao/'));
    dom.window.close();
});

test("unresolved app address disables batch instead of opening a wrong destination", () => {
    const {dom, doc, boxes, click, opened} = setup({url: 'about:blank', referrer: undefined});
    assert.ok(boxes.every(b => b.disabled));
    click('select-page');
    assert.equal(doc.getElementById('open-selected').disabled, true);
    assert.equal(opened.length, 0);
    dom.window.close();
});
