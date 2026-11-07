/* First-run preparation and portable data, shared by the home settings surfaces. */
let storySetupState = null;
const setupEl = id => document.getElementById(id);
async function setupRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '暂时没有连到店内服务，请再试一次。');
  return data;
}
async function refreshStorySetup() {
  setupEl('setupStatus').textContent = '正在检测本机的故事助手…';
  setupEl('setupRefresh').disabled = true;
  try {
    const state = await setupRequest('/api/setup');
    storySetupState = state;
    setupEl('setupStatus').textContent = state.message;
    setupEl('storyStatus').textContent = state.ready ? '故事助手已准备好' : '新故事需要先准备故事助手，试听与词卡随时可用';
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
    select.disabled = state.locked || !state.models.length;
    setupEl('modelSave').disabled = state.locked || !state.models.length;
    setupEl('modelLocked').classList.toggle('hidden', !state.locked);
    setupEl('setupSteps').open = !state.ready;
    setupEl('voiceStatus').textContent = state.audio === 'kokoro' ? '配音已就绪 · Kokoro' : state.audio === 'system'
      ? '配音已就绪 · 系统语音，无需额外下载' : '目前生成文字故事，离线招待仍可播放。可以安装系统英语语音或配置 Kokoro 后再生成有声故事。';
  } catch (error) {
    storySetupState = null;
    setupEl('setupStatus').textContent = error.message;
    setupEl('storyStatus').textContent = '暂时无法检测助手，你可以先试听或翻词卡';
  } finally { setupEl('setupRefresh').disabled = false; }
}
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
