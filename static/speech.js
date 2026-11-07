/* Render generated speech as text, with phrases kept together for lookup. */
function cafeEscape(text) {
  return String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function cafeTarget(token, words) {
  return words.find(word => {
    const w = word.toLowerCase();
    if (token === w) return true;
    if (/[ -]/.test(w) || w.length < 3) return false;
    const forms = [w + 's', w + 'es', w + 'ed', w + 'ing'];
    if (w.endsWith('e')) forms.push(w + 'd', w.slice(0, -1) + 'ing');
    if (w.endsWith('y')) forms.push(w.slice(0, -1) + 'ies', w.slice(0, -1) + 'ied');
    if (/[aeiou][b-df-hj-np-tv-z]$/.test(w)) forms.push(w + w.slice(-1) + 'ed', w + w.slice(-1) + 'ing');
    return forms.includes(token);
  });
}
function cafeSpeech(text, targets) {
  const words = targets.map(t => typeof t === 'string' ? t : t.word).filter(Boolean);
  const phrases = words.filter(w => /[ -]/.test(w)).sort((a,b) => b.length-a.length)
    .map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp((phrases.length ? '\\b(?:' + phrases.join('|') + ')\\b|' : '') + "[A-Za-z][A-Za-z']*|[&<>\\\"]", 'gi');
  return String(text).replace(pattern, token => {
    if (!/^[A-Za-z]/.test(token)) return cafeEscape(token);
    const lower = token.toLowerCase();
    const target = cafeTarget(lower, words);
    if (!target && token.length <= 2) return cafeEscape(token);
    return `<span class="wclick${target ? ' tword' : ''}" data-word="${cafeEscape(target || lower)}">${cafeEscape(token)}</span>`;
  });
}
