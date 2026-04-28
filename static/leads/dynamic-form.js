/* Form dinâmico — render baseado em fields[].
 *
 * Tipos suportados: text, number, date, textarea, select, radio, repeater, select_cnae.
 * Comportamentos especiais por field_key:
 *    - termina em "cep"     → máscara 00000-000
 *    - termina em "estado"  → autocomplete UF (lista local de 27 estados)
 *    - termina em "cidade"  → autocomplete IBGE (proxy /api/leads/ibge/cidades/<UF>)
 *    - termina em "cnae" ou field_type "select_cnae" → autocomplete IBGE CNAE
 *
 * Cache em módulo:
 *    cityCache: Map<UF, string[]>
 *    cnaeCache: Item[] | null
 */

(function () {

  const UFS = [
    ['AC', 'Acre'], ['AL', 'Alagoas'], ['AP', 'Amapá'], ['AM', 'Amazonas'], ['BA', 'Bahia'],
    ['CE', 'Ceará'], ['DF', 'Distrito Federal'], ['ES', 'Espírito Santo'], ['GO', 'Goiás'],
    ['MA', 'Maranhão'], ['MT', 'Mato Grosso'], ['MS', 'Mato Grosso do Sul'], ['MG', 'Minas Gerais'],
    ['PA', 'Pará'], ['PB', 'Paraíba'], ['PR', 'Paraná'], ['PE', 'Pernambuco'], ['PI', 'Piauí'],
    ['RJ', 'Rio de Janeiro'], ['RN', 'Rio Grande do Norte'], ['RS', 'Rio Grande do Sul'],
    ['RO', 'Rondônia'], ['RR', 'Roraima'], ['SC', 'Santa Catarina'], ['SP', 'São Paulo'],
    ['SE', 'Sergipe'], ['TO', 'Tocantins'],
  ];

  const cityCache = new Map();   // UF -> [nomes]
  let cnaeCache = null;          // Item[] | null

  async function loadCities(uf) {
    if (cityCache.has(uf)) return cityCache.get(uf);
    try {
      const r = await fetch(`/api/leads/ibge/cidades/${encodeURIComponent(uf)}`);
      if (!r.ok) return [];
      const data = await r.json();
      if (Array.isArray(data)) {
        cityCache.set(uf, data);
      }
    } catch (e) { /* offline — retorna vazio */ }
    return cityCache.get(uf) || [];
  }

  async function loadCnaes() {
    if (cnaeCache) return cnaeCache;
    try {
      const r = await fetch('https://servicodados.ibge.gov.br/api/v2/cnae/subclasses');
      const data = await r.json();
      if (Array.isArray(data)) {
        cnaeCache = data.map(item => {
          // Formata "0111301" como "0111-3/01"
          let id = item.id;
          let formatted = id;
          if (id.length === 7) {
            formatted = `${id.substring(0, 4)}-${id.substring(4, 5)}/${id.substring(5, 7)}`;
          }
          const fullText = `${formatted} - ${item.descricao}`;
          return { label: fullText, value: fullText };
        });
      }
    } catch (e) {
      cnaeCache = [];
    }
    return cnaeCache;
  }

  // ---------- builders ----------

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'class') e.className = v;
      else if (k === 'on') for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
      else if (v != null) e.setAttribute(k, v);
    }
    children.flat().forEach(c => {
      if (c == null) return;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    });
    return e;
  }

  function maskCep(input) {
    input.addEventListener('input', () => {
      const d = input.value.replace(/\D/g, '').slice(0, 8);
      input.value = d.length > 5 ? d.slice(0, 5) + '-' + d.slice(5) : d;
    });
  }

  function maskCnpj(input) {
    input.maxLength = 18; // XX.XXX.XXX/XXXX-XX
    input.placeholder = 'XX.XXX.XXX/XXXX-XX';
    input.addEventListener('input', () => {
      const d = input.value.replace(/\D/g, '').slice(0, 14);
      let v = d;
      if (d.length > 12) v = d.slice(0,2)+'.'+d.slice(2,5)+'.'+d.slice(5,8)+'/'+d.slice(8,12)+'-'+d.slice(12);
      else if (d.length > 8)  v = d.slice(0,2)+'.'+d.slice(2,5)+'.'+d.slice(5,8)+'/'+d.slice(8);
      else if (d.length > 5)  v = d.slice(0,2)+'.'+d.slice(2,5)+'.'+d.slice(5);
      else if (d.length > 2)  v = d.slice(0,2)+'.'+d.slice(2);
      input.value = v;
    });
  }

  function autocomplete(input, getOptions, onPick) {
    const wrap = el('div', { class: 'autocomplete-wrap position-relative' });
    if (input.parentNode) {
      input.parentNode.insertBefore(wrap, input);
    }
    wrap.appendChild(input);
    const list = el('div', { class: 'autocomplete-list' });
    wrap.appendChild(list);

    let active = -1;
    let lastOpts = [];

    async function refresh() {
      const q = input.value.trim().toLowerCase();
      const all = await getOptions();
      lastOpts = (q
        ? all.filter(o => (o.label || o).toString().toLowerCase().includes(q))
        : all).slice(0, 50);
      list.innerHTML = '';
      lastOpts.forEach((o, i) => {
        const item = el('div', { class: 'item' + (i === active ? ' active' : '') }, o.label || String(o));
        item.addEventListener('mousedown', (ev) => {
          ev.preventDefault();
          input.value = o.value || o.label || String(o);
          if (onPick) onPick(o);
          list.classList.remove('open');
        });
        list.appendChild(item);
      });
      list.classList.toggle('open', lastOpts.length > 0);
    }

    input.addEventListener('focus', refresh);
    input.addEventListener('input', refresh);
    input.addEventListener('blur', () => setTimeout(() => list.classList.remove('open'), 150));
    input.addEventListener('keydown', (e) => {
      if (!list.classList.contains('open')) return;
      if (e.key === 'ArrowDown') { active = Math.min(active + 1, lastOpts.length - 1); refresh(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { active = Math.max(active - 1, 0); refresh(); e.preventDefault(); }
      else if (e.key === 'Enter' && active >= 0) {
        e.preventDefault();
        const o = lastOpts[active];
        input.value = o.value || o.label || String(o);
        if (onPick) onPick(o);
        list.classList.remove('open');
      }
    });
    return wrap;
  }

  function fieldInput(f, value, ctx = {}) {
    const key = f.field_key || f.key || '';
    const lk = key.toLowerCase();
    const baseAttrs = { name: key, class: 'form-control form-field', 'data-key': key };

    // Repeater
    if (f.field_type === 'repeater') {
      return repeaterField(f, Array.isArray(value) ? value : []);
    }

    // Select / radio
    if (f.field_type === 'select' || f.field_type === 'radio') {
      const sel = el('select', { ...baseAttrs, class: 'form-select form-field' });
      sel.appendChild(el('option', { value: '' }, '— selecione —'));
      (f.options || []).forEach(o => {
        const lab = typeof o === 'string' ? o : (o.label || o.key || '');
        const val = typeof o === 'string' ? o : (o.key || o.label || '');
        const opt = el('option', { value: val }, lab);
        if (String(value) === String(val)) opt.selected = true;
        sel.appendChild(opt);
      });
      return sel;
    }

    // Textarea
    if (f.field_type === 'textarea') {
      const ta = el('textarea', { ...baseAttrs, rows: 3 });
      ta.value = value || '';
      return ta;
    }

    // Number / date / text — base
    let input = el('input', {
      ...baseAttrs,
      type: f.field_type === 'number' ? 'number' : f.field_type === 'date' ? 'date' : 'text',
      value: value || '',
    });

    // Comportamentos especiais
    if (lk.endsWith('cep')) {
      input.placeholder = '00000-000';
      input.maxLength = 9;
      maskCep(input);
    } else if (lk.endsWith('cnpj')) {
      maskCnpj(input);
    } else if (lk.endsWith('estado')) {
      input = autocomplete(
        input,
        async () => UFS.map(([uf, nome]) => ({ label: `${uf} — ${nome}`, value: uf })),
        (o) => {
          // notifica os campos "cidade" no mesmo escopo
          const scope = ctx.scope || document;
          scope.querySelectorAll('[data-key$="cidade"]').forEach(c => c.dataset.uf = o.value);
        },
      );
    } else if (lk.endsWith('cidade')) {
      const originalInput = input; // preserva ref antes do wrap
      input = autocomplete(input, async () => {
        const uf = originalInput.dataset.uf
          || (ctx.scope || document).querySelector('[data-key$="estado"]')?.value;
        if (!uf) return [];
        const cities = await loadCities(uf);
        return cities.map(c => ({ label: c, value: c }));
      });
    } else if (f.field_type === 'select_cnae' || lk.endsWith('cnae')) {
      input = autocomplete(input, async () => {
        const items = await loadCnaes();
        return items;
      });
    }

    return input;
  }

  function repeaterField(f, values) {
    const subFields = f.options || [];
    const wrap = el('div', { class: 'repeater', 'data-key': f.field_key });
    const items = el('div', { class: 'repeater-items' });
    wrap.appendChild(items);

    function addItem(initial = {}) {
      const block = el('div', { class: 'repeater-item' });
      const remove = el('button', {
        type: 'button', class: 'btn btn-sm btn-link text-danger remove-item',
        on: { click: () => block.remove() },
      });
      remove.innerHTML = '<i class="bi bi-x-lg"></i>';
      block.appendChild(remove);
      const grid = el('div', { class: 'row g-2' });
      block.appendChild(grid);

      subFields.forEach(sf => {
        const col = el('div', { class: 'col-md-6' });
        col.appendChild(el('label', { class: 'form-label small text-muted' }, sf.label || sf.key));
        col.appendChild(fieldInput(sf, initial[sf.key || sf.field_key] || '', { scope: block }));
        grid.appendChild(col);
      });
      items.appendChild(block);
    }

    (values.length ? values : []).forEach(v => addItem(v));
    if (!values.length) addItem();

    const addBtn = el('button', {
      type: 'button', class: 'btn btn-sm btn-outline-primary mt-2',
      on: { click: () => addItem() },
    });
    addBtn.innerHTML = '<i class="bi bi-plus"></i> Adicionar';
    wrap.appendChild(addBtn);

    return wrap;
  }

  function collectField(f, hostScope) {
    const key = f.field_key;
    if (f.field_type === 'repeater') {
      const subFields = f.options || [];
      const items = hostScope.querySelectorAll(`.repeater[data-key="${cssEsc(key)}"] .repeater-item`);
      const arr = [];
      items.forEach(it => {
        const obj = {};
        subFields.forEach(sf => {
          const ipt = it.querySelector(`[data-key="${cssEsc(sf.key || sf.field_key)}"]`);
          if (ipt) obj[sf.key || sf.field_key] = ipt.value;
        });
        arr.push(obj);
      });
      return arr;
    }
    const ipt = hostScope.querySelector(`:scope > .field-block [data-key="${cssEsc(key)}"], :scope [data-key="${cssEsc(key)}"]`);
    return ipt ? ipt.value : '';
  }

  function cssEsc(s) {
    return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/"/g, '\\"');
  }

  // ---------- API pública ----------

  window.DynamicForm = {
    render(host, fields, values) {
      host.innerHTML = '';
      let lastSection = null;
      let grid = null;

      fields.forEach(f => {
        if (f.section && f.section !== lastSection) {
          host.appendChild(el('div', { class: 'field-section w-100' }, f.section));
          lastSection = f.section;
          grid = el('div', { class: 'row g-3' });
          host.appendChild(grid);
        } else if (!grid) {
          grid = el('div', { class: 'row g-3' });
          host.appendChild(grid);
        }

        const isFullWidth = (f.field_type === 'textarea' || f.field_type === 'repeater');
        const colClass = isFullWidth ? 'col-12 field-block' : 'col-md-6 field-block';
        const block = el('div', { class: colClass }, '');
        block.style.marginBottom = '0';

        const lbl = el('label', { class: 'form-label small text-muted fw-semibold mb-1' }, f.label);
        if (f.required) lbl.innerHTML += ' <span class="text-danger">*</span>';
        block.appendChild(lbl);
        block.appendChild(fieldInput(f, values[f.field_key] || '', { scope: host }));
        if (f.help_text) block.appendChild(el('small', { class: 'text-muted' }, f.help_text));

        grid.appendChild(block);
      });
    },

    collect(host, fields) {
      const out = {};
      fields.forEach(f => { out[f.field_key] = collectField(f, host); });
      return out;
    },
  };
})();
