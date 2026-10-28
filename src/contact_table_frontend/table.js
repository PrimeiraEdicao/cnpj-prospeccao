(() => {
    "use strict";
    const boxes = [...document.querySelectorAll(".row-select")];
    const selectAll = document.getElementById("select-all");
    const selectPage = document.getElementById("select-page");
    const clear = document.getElementById("clear-selection");
    const open = document.getElementById("open-selected");
    const count = document.getElementById("selection-count");
    const status = document.getElementById("batch-status");
    let appUrl;
    try {
        // srcdoc herda a base da página; referrer atende versões sem st.context.url.
        appUrl = new URL(document.body.dataset.appUrl || document.referrer || document.baseURI);
        if (!["https:", "http:"].includes(appUrl.protocol)) throw new Error("URL inválida");
    } catch (_) {
        appUrl = undefined;
        status.hidden = false;
        status.textContent = "Não foi possível identificar o endereço do aplicativo. Atualize a página para abrir os contatos.";
    }
    function contactUrl(query) {
        const url = new URL(appUrl.href);
        url.search = query;
        url.hash = "";
        return url.href;
    }
    for (const link of document.querySelectorAll("a[data-contact-query]")) {
        if (appUrl) link.href = contactUrl(link.dataset.contactQuery);
        else link.removeAttribute("href");
    }
    if (!appUrl) boxes.forEach(box => { box.disabled = true; });
    const available = () => boxes.filter(box => !box.disabled);
    const selected = () => available().filter(box => box.checked);
    function update() {
        const n = selected().length;
        count.textContent = n ? `${n} empresa${n === 1 ? " selecionada" : "s selecionadas"}` : "Nenhuma empresa selecionada";
        open.textContent = `Abrir WhatsApps selecionados (${n})`;
        open.disabled = n === 0;
        clear.disabled = n === 0;
        selectPage.disabled = available().length === 0;
        selectAll.disabled = available().length === 0;
        selectAll.checked = n > 0 && n === available().length;
        selectAll.indeterminate = n > 0 && n < available().length;
        boxes.forEach(box => box.closest("tr").classList.toggle("selected", box.checked));
    }
    boxes.forEach(box => box.addEventListener("change", update));
    selectAll.addEventListener("change", () => {
        available().forEach(box => { box.checked = selectAll.checked; });
        update();
    });
    selectPage.addEventListener("click", () => {
        available().forEach(box => { box.checked = true; });
        update();
    });
    clear.addEventListener("click", () => {
        boxes.forEach(box => { box.checked = false; });
        update();
    });
    open.addEventListener("click", () => {
        let opened = 0;
        let blocked = 0;
        // Síncrono no clique: não abrir abas após rerun do Python, timer ou await.
        for (const box of selected()) {
            let tab;
            try {
                tab = window.open("about:blank", "_blank");
                if (!tab) { blocked++; continue; }
                tab.opener = null;
                tab.location.replace(contactUrl(box.dataset.contactQuery));
                opened++;
                box.checked = false;
                box.disabled = true;
                box.closest("tr").querySelector(".open-status").textContent = "Aba aberta";
            } catch (_) {
                if (tab) tab.close();
                blocked++;
            }
        }
        status.hidden = false;
        status.textContent = `${opened} aba(s) aberta(s). ` + (blocked
            ? `${blocked} contato(s) continuam selecionados porque o navegador bloqueou a abertura. Permita pop-ups deste aplicativo e clique novamente para abrir somente os restantes.`
            : "Confira as mensagens nas abas do WhatsApp e confirme cada envio.");
        update();
    });
    update();
})();
