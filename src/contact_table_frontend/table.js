"use strict";
window.initContactTable = function initContactTable(options = {}) {
    const boxes = [...document.querySelectorAll(".row-select")];
    const selectAll = document.getElementById("select-all");
    const selectPage = document.getElementById("select-page");
    const clear = document.getElementById("clear-selection");
    const open = document.getElementById("open-selected");
    const mark = document.getElementById("mark-contacted");
    const count = document.getElementById("selection-count");
    const status = document.getElementById("batch-status");
    const available = () => boxes.filter(box => !box.disabled);
    const selected = () => available().filter(box => box.checked);
    const pending = () => selected().filter(box => box.dataset.opened !== "true");
    function whatsappUrl(element) {
        const data = JSON.parse(element.dataset.contact);
        if (!/^\d{10,15}$/.test(data.phone)) throw new Error("Telefone inválido");
        const hour = Number(new Intl.DateTimeFormat("en-GB", {
            timeZone: "America/Sao_Paulo", hour: "numeric", hourCycle: "h23"
        }).format(new Date()));
        const greeting = hour >= 6 && hour < 12 ? "Bom dia" : hour < 18 && hour >= 12 ? "Boa tarde" : "Boa noite";
        const values = {saudacao: data.salutation || greeting, nome: data.name || "a pessoa responsável", remetente: data.sender.trim()};
        const message = data.template.replace(/{{|}}|{(saudacao|nome|remetente)}/g,
            (match, field) => match === "{{" ? "{" : match === "}}" ? "}" : values[field]);
        const url = new URL("https://web.whatsapp.com/send");
        url.search = new URLSearchParams({phone: data.phone, text: message}).toString();
        return url.href;
    }
    function update() {
        const n = selected().length;
        count.textContent = n ? `${n} empresa${n === 1 ? " selecionada" : "s selecionadas"}` : "Nenhuma empresa selecionada";
        open.textContent = `Abrir WhatsApps selecionados (${pending().length})`;
        open.disabled = pending().length === 0;
        mark.disabled = n === 0;
        clear.disabled = n === 0;
        selectPage.disabled = available().length === 0;
        selectAll.disabled = available().length === 0;
        selectAll.checked = n > 0 && n === available().length;
        selectAll.indeterminate = n > 0 && n < available().length;
        boxes.forEach(box => box.closest("tr").classList.toggle("selected", box.checked));
    }
    for (const link of document.querySelectorAll("a[data-contact]")) {
        link.addEventListener("click", () => {
            link.href = whatsappUrl(link);
            const box = link.closest("tr").querySelector(".row-select");
            if (box && !box.disabled) { box.checked = true; update(); }
        });
    }
    boxes.forEach(box => box.addEventListener("change", update));
    selectAll.addEventListener("change", () => {
        available().forEach(box => { box.checked = selectAll.checked; }); update();
    });
    selectPage.addEventListener("click", () => {
        available().forEach(box => { box.checked = true; }); update();
    });
    clear.addEventListener("click", () => {
        boxes.forEach(box => { box.checked = false; }); update();
    });
    open.addEventListener("click", () => {
        let opened = 0;
        let blocked = 0;
        for (const box of pending()) {
            let tab;
            try {
                tab = window.open("about:blank", "_blank");
                if (!tab) { blocked++; continue; }
                tab.opener = null;
                tab.location.replace(whatsappUrl(box));
                opened++;
                box.dataset.opened = "true";
                box.closest("tr").querySelector(".open-status").textContent = "Aba aberta · aguardando confirmação";
            } catch (_) {
                if (tab) tab.close();
                blocked++;
            }
        }
        status.hidden = false;
        status.textContent = `${opened} aba(s) aberta(s). ` + (blocked
            ? `${blocked} bloqueada(s). Permita pop-ups e clique novamente para abrir somente as restantes. ` : "")
            + "Depois das conversas, marque as empresas efetivamente contatadas. A abertura não confirma envio.";
        update();
    });
    mark.addEventListener("click", () => {
        const cnpjs = selected().map(box => JSON.parse(box.dataset.contact).cnpj);
        if (!cnpjs.length || !options.onMark) return;
        mark.disabled = true;
        open.disabled = true;
        status.hidden = false;
        status.textContent = "Salvando empresas contatadas…";
        options.onMark(cnpjs);
    });
    update();
    return {refresh: update};
};
if (document.getElementById("selection-count")) window.initContactTable(window.contactTableOptions || {});
