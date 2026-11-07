/* First-run preparation and portable data, shared by the home settings surfaces. */
let storySetupState = null;
let setupPoll = null;
let setupChoiceSet = false;
const setupEl = id => document.getElementById(id);
async function setupRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '暂时没有连到店内服务，请再试一次。');
  return data;
}
async function refreshStorySetup() {
  clearTimeout(setupPoll);
  if (!storySetupState) setupEl('setupStatus').textContent = '正在检测本机的故事助手…';
  setupEl('setupRefresh').disabled = true;
  try {
    const state = await setupRequest('/api/setup');
    storySetupState = state;
    const install = state.install || {active:false, phase:'idle'};
    const options = state.options || {supported:false, catalog:{}, engine_bytes:0};
    setupEl('setupStatus').textContent = install.message || state.message;
    setupEl('storyStatus').textContent = install.active ? '故事助手正在准备，你可以先试听或翻词卡' : state.ready ? '故事助手已准备好' : '点故事设置，一键准备你的助手';
    if (!setupChoiceSet) {
      setupEl('setupProfile').value = ['paused','error'].includes(install.phase) ? install.profile : options.recommended || 'standard';
      setupChoiceSet = true;
    }
    setupEl('setupProfile').disabled = install.active || state.locked;
    setupEl('setupPrepare').disabled = install.active || state.locked || !options.supported;
    setupEl('setupPrepare').textContent = install.active ? '正在准备…' : ['paused','error'].includes(install.phase) ? '继续准备' : state.ready ? '换用所选助手' : '一键准备';
    setupEl('setupCancel').classList.toggle('hidden', !install.active);
    setupEl('setupCancel').disabled = false;
    setupEl('setupCancel').textContent = install.phase === 'checking' ? '取消准备' : '暂停下载';
    setupEl('setupProgressBox').classList.toggle('hidden', !install.active && !['paused','error'].includes(install.phase));
    if (install.total > 0) {
      setupEl('setupProgress').max = install.total;
      setupEl('setupProgress').value = Math.min(install.completed, install.total);
      setupEl('setupProgressText').textContent = `${formatBytes(install.completed)} / ${formatBytes(install.total)}`;
    } else {
      setupEl('setupProgress').removeAttribute('value');
      setupEl('setupProgressText').textContent = install.active ? '你可以先回店里，准备会继续进行。' : '';
    }
    updateSetupSize();
    const select = setupEl('modelSelect');
    select.replaceChildren();
    const blank = document.createElement('option');
    blank.value = ''; blank.textContent = state.models.length ? '请选择本地聊天模型' : '暂未找到本地模型';
    select.append(blank);
    for (const name of state.models) {
      const option = document.createElement('option');
      option.value = name; option.textContent = name;
      select.append(option);
    }
    select.value = state.model;
    select.disabled = state.locked || install.active || !state.models.length;
    setupEl('modelSave').disabled = state.locked || install.active || !state.models.length;
    setupEl('modelLocked').classList.toggle('hidden', !state.locked);
    setupEl('voiceStatus').textContent = state.audio === 'kokoro' ? '配音已就绪 · Kokoro' : state.audio === 'system'
      ? '配音已就绪 · 系统语音，无需额外下载' : '目前生成文字故事，离线招待仍可播放。可以安装系统英语语音或配置 Kokoro 后再生成有声故事。';
  } catch (error) {
    storySetupState = null;
    setupEl('setupStatus').textContent = error.message;
    setupEl('storyStatus').textContent = '暂时无法检测助手，你可以先试听或翻词卡';
  } finally {
    setupEl('setupRefresh').disabled = false;
    if (storySetupState?.install?.active) setupPoll = setTimeout(refreshStorySetup, 1000);
  }
}
function formatBytes(bytes) { return bytes >= 1e9 ? (bytes / 1e9).toFixed(2) + ' GB' : Math.round(bytes / 1e6) + ' MB'; }
function updateSetupSize() {
  const options = storySetupState?.options;
  if (!options) return;
  const profile = options.catalog[setupEl('setupProfile').value];
  setupEl('setupDownloadSize').textContent = !options.supported ? options.reason : profile
    ? `模型约 ${formatBytes(profile.bytes)}` + (options.engine_bytes ? `，助手引擎约 ${formatBytes(options.engine_bytes)}` : '；已有引擎会自动复用') + '。已下载的内容会复用。'
    : '';
}
setupEl('setupProfile').addEventListener('change', updateSetupSize);
setupEl('setupPrepare').addEventListener('click', async () => {
  setupEl('setupPrepare').disabled = true;
  try {
    await setupRequest('/api/setup/prepare', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({profile:setupEl('setupProfile').value})});
    await refreshStorySetup();
  } catch (error) {
    setupEl('setupStatus').textContent = error.message;
    setupEl('setupPrepare').disabled = false;
  }
});
setupEl('setupCancel').addEventListener('click', async () => {
  setupEl('setupCancel').disabled = true;
  try {
    await setupRequest('/api/setup/cancel', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
    await refreshStorySetup();
  } catch (error) { setupEl('setupStatus').textContent = error.message; setupEl('setupCancel').disabled = false; }
});
function openStorySetup() {
  if (!setupEl('cfgModal').classList.contains('hidden')) closeCafeDialog('cfgModal');
  openCafeDialog('setupModal', 'setupClose');
  refreshStorySetup();
}
document.querySelectorAll('[data-story-setup]').forEach(el => el.addEventListener('click', openStorySetup));
setupEl('setupRefresh').addEventListener('click', refreshStorySetup);
setupEl('setupClose').addEventListener('click', () => closeCafeDialog('setupModal'));
setupEl('modelSave').addEventListener('click', async () => {
  setupEl('modelSave').disabled = true;
  try {
    await setupRequest('/api/setup', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({model: setupEl('modelSelect').value})});
    await refreshStorySetup();
    setupEl('setupStatus').textContent = '已保存，回到窗边就可以点词了。';
  } catch (error) { setupEl('setupStatus').textContent = error.message; }
  finally { setupEl('modelSave').disabled = !!storySetupState?.locked; }
});
setupEl('deckFile').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.apkg') || file.size > 512 * 1024 * 1024) {
    setupEl('dataStatus').textContent = '请选择 512 MB 以内的 .apkg 词包。'; event.target.value = ''; return;
  }
  event.target.disabled = true;
  setupEl('dataStatus').textContent = '正在整理词包，大词库可能需要一点时间…';
  try {
    const result = await setupRequest('/api/decks/import?name=' + encodeURIComponent(file.name), {method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:file});
    setupEl('dataStatus').textContent = `已导入 ${result.words} 个词。重新打开词卡或调一调难度，就能使用新词库。`;
  } catch (error) { setupEl('dataStatus').textContent = error.message; }
  finally { event.target.disabled = false; event.target.value = ''; }
});
setupEl('restoreFile').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  event.target.disabled = true;
  try {
    if (file.size > 32 * 1024 * 1024) throw new Error('请选择 32 MB 以内的记录备份。');
    const data = JSON.parse(await file.text());
    await setupRequest('/api/restore', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    setupEl('dataStatus').textContent = '学习记录已恢复。重新打开词卡即可继续。';
  } catch (error) { setupEl('dataStatus').textContent = error instanceof SyntaxError ? '这不是有效的学习记录备份。' : error.message; }
  finally { event.target.disabled = false; event.target.value = ''; }
});
