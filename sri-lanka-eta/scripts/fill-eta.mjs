/**
 * 斯里兰卡 ETA 电子签证自动填表脚本
 * 
 * 使用方法：
 *   1. 准备 payload.json（或自定义 JSON 文件）
 *   2. npm install playwright && npx playwright install webkit
 *   3. node scripts/fill-eta.mjs --payload payload.json
 * 
 * 注意：
 *   - 脚本会在 Review 页面暂停，不会自动提交
 *   - 所有 JS alert/confirm 弹窗会被自动接受
 *   - 截图保存在当前目录
 */

import { webkit } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const DEFAULT_PAYLOAD_PATH = path.resolve(__dirname, '../payload.json');
const REQUIRED_PAYLOAD_FIELDS = [
    'surname',
    'otherNames',
    'title',
    'dob',
    'gender',
    'nationality',
    'countryOfBirth',
    'occupation',
    'passportNo',
    'passportIssued',
    'passportExpiry',
    'visaDays',
    'arrivalDate',
    'purposeOfVisit',
    'departureCountry',
    'addressLine1',
    'city',
    'state',
    'country',
    'addressInSriLanka',
    'email',
    'telephone',
];

const wait = (ms) => new Promise(r => setTimeout(r, ms));

function resolvePayloadPath() {
    const payloadArgIndex = process.argv.indexOf('--payload');
    if (payloadArgIndex >= 0 && process.argv[payloadArgIndex + 1]) {
        return path.resolve(process.cwd(), process.argv[payloadArgIndex + 1]);
    }
    return DEFAULT_PAYLOAD_PATH;
}

function loadPayload(payloadPath) {
    if (!fs.existsSync(payloadPath)) {
        throw new Error(`Payload file not found: ${payloadPath}`);
    }

    const raw = fs.readFileSync(payloadPath, 'utf8');
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error(`Invalid payload JSON object: ${payloadPath}`);
    }
    return parsed;
}

function validatePayload(data) {
    const missing = REQUIRED_PAYLOAD_FIELDS.filter((key) => {
        const value = data[key];
        return value === undefined || value === null || String(value).trim() === '';
    });
    if (missing.length > 0) {
        throw new Error(`Missing required payload fields: ${missing.join(', ')}`);
    }
}

async function main() {
    const payloadPath = resolvePayloadPath();
    const data = loadPayload(payloadPath);
    validatePayload(data);

    console.log(`📦 Payload: ${payloadPath}`);
    console.log('🚀 启动浏览器...');
    const browser = await webkit.launch({ headless: false, slowMo: 50 });
    const context = await browser.newContext({ viewport: { width: 1400, height: 900 }, locale: 'en-US' });
    const page = await context.newPage();

    // 核心：全局 dialog 处理器
    page.on('dialog', async (dialog) => {
        console.log(`📢 [${dialog.type()}] ${dialog.message().substring(0, 120)}`);
        await dialog.accept();
        console.log('   ✅ 弹窗已接受');
    });

    // 监听请求：捕获表单提交的 POST 数据
    page.on('request', (request) => {
        if (request.method() === 'POST' && request.url().includes('etaNavServ')) {
            const postData = request.postData();
            if (postData && postData.length > 100) {
                console.log('\n📤 ========== 表单 POST 数据 ==========');
                // 解析 URL-encoded 数据为可读格式
                const params = new URLSearchParams(postData);
                for (const [key, value] of params.entries()) {
                    console.log(`   ${key} = ${value}`);
                }
                console.log('========================================\n');
            }
        }
    });

    try {
        // Step 1: 条款页
        console.log('\n📋 Step 1: 打开 ETA 首页...');
        await page.goto('https://eta.gov.lk/etaslvisa/etaNavServ', { waitUntil: 'load', timeout: 30000 });
        await wait(2000);
        console.log('   点击 I Agree（自动提交）...');
        await page.evaluate(() => {
            const r = document.querySelector('input[name="terms"][value="yes"]');
            if (r) { r.checked = true; r.click(); }
        });
        await page.waitForLoadState('load');
        await wait(2000);
        console.log('   ✅ 条款已同意');

        // Step 2: Tourist Individual
        console.log('\n📋 Step 2: 选择 Tourist ETA - Individual...');
        await page.evaluate(() => { document.getElementById('1').click(); });
        await page.waitForLoadState('load');
        // 显式等待表单第一个字段出现
        await page.waitForSelector('#surname', { timeout: 30000 });
        await wait(1000);
        console.log('   ✅ 已进入表单页');

        // Step 3: 填写表单
        console.log('\n📋 Step 3: 填写表单...');

        // --- 基本信息 ---
        await page.fill('#surname', data.surname);
        await page.fill('#othernames', data.otherNames);
        await page.selectOption('#title', data.title);
        await setDateField(page, 'bdate', data.dob);
        await setDateField(page, 'reenteredbdate', data.dob);
        await page.selectOption('#gender', data.gender);
        await page.selectOption('#national', data.nationality);
        await page.selectOption('#conbirth', data.countryOfBirth);
        await page.fill('#occupation', data.occupation);
        console.log('   ✅ 基本信息');

        // --- 护照（绕过 AJAX 校验，直接设值）---
        // 先用 fill 触发一次 onchange 让 AJAX 跑完，接受弹窗
        await page.fill('#passportno', data.passportNo);
        await page.locator('#passportno').blur();
        await wait(2000); // 等待 AJAX 返回 + dialog 被自动接受
        // AJAX 回调可能清空了字段并设 idHiddenPassOk='0'，强制恢复
        await page.evaluate((ppNo) => {
            document.getElementById('passportno').value = ppNo;
            document.getElementById('reenteredpassportno').value = ppNo;
            // 强制标记护照校验通过
            const hiddenPass = document.getElementById('idHiddenPassOk');
            if (hiddenPass) hiddenPass.value = '1';
        }, data.passportNo);
        await wait(500);
        await setDateField(page, 'pidate', data.passportIssued);
        await setDateField(page, 'pedate', data.passportExpiry);
        console.log('   ✅ 护照信息');

        // --- 旅行信息（Visa Days 触发 confirm 弹窗）---
        console.log('   ⚠️  选择签证天数（弹窗将被自动接受）...');
        await page.selectOption('#RequestedVisaDays', data.visaDays);
        await wait(1500);
        await page.selectOption('#fromDeparture', data.departureCountry);
        await wait(500);
        await setDateField(page, 'iadate', data.arrivalDate);
        await page.selectOption('#puofvisit', data.purposeOfVisit);
        await page.fill('#depcity', data.departureCity);
        if (data.airline) await page.fill('#airline', data.airline);
        if (data.flightNo) await page.fill('#flightno', data.flightNo);
        console.log('   ✅ 旅行信息');

        // --- 联系方式（必须用 click+type，fill 无效）---
        await typeInField(page, '#addone', data.addressLine1);
        await typeInField(page, '#city', data.city);
        await typeInField(page, '#state', data.state);
        await page.selectOption('#adcountry', data.country);
        await typeInField(page, '#addinsl', data.addressInSriLanka);
        await typeInField(page, '#email', data.email);
        await typeInField(page, '#reenteremail', data.email);
        await typeInField(page, '#telephon', data.telephone);
        if (data.mobile) {
            try { await typeInField(page, '#mobileno', data.mobile); } catch (e) { }
        }
        console.log('   ✅ 联系方式');

        // --- 声明（先点 YES 触发 alert 弹窗被自动接受，再点 NO）---
        for (const qn of ['QN1', 'QN2', 'QN3']) {
            // 先点 YES（会触发 "You are not eligible" alert，dialog handler 自动接受）
            await page.click(`#vlrY${qn}`);
            await wait(800);
            // 再点 NO
            await page.click(`#vlrN${qn}`);
            await wait(300);
        }
        await page.check('input[name="conf"]');
        console.log('   ✅ 声明 & 确认');

        // 提交前预检：打印关键字段状态
        const preCheck = await page.evaluate(() => {
            return {
                passportno: document.getElementById('passportno')?.value,
                reenteredpassportno: document.getElementById('reenteredpassportno')?.value,
                idHiddenPassOk: document.getElementById('idHiddenPassOk')?.value,
                qn1N: document.getElementById('vlrNQN1')?.checked,
                qn2N: document.getElementById('vlrNQN2')?.checked,
                qn3N: document.getElementById('vlrNQN3')?.checked,
                conf: document.querySelector('input[name="conf"]')?.checked,
                bdate: document.getElementById('bdate')?.value,
                fromDeparture: document.getElementById('fromDeparture')?.value,
            };
        });
        console.log('\n🔍 提交前预检:', JSON.stringify(preCheck, null, 2));

        // 截图
        await page.screenshot({ path: 'eta-form-filled.png', fullPage: true });
        console.log('📸 表单截图: eta-form-filled.png');

        // Step 4: 提交
        console.log('\n📋 Step 4: 点击 Next...');
        // 并行等待：点击按钮 + 等待导航
        await Promise.all([
            page.waitForNavigation({ waitUntil: 'load', timeout: 30000 }).catch(() => { }),
            page.evaluate(() => {
                const btn = document.getElementById('submitButton');
                if (btn) btn.click();
            }),
        ]);
        await wait(3000);

        // Step 5: Review 页
        console.log('\n📋 Step 5: Review 页面...');
        await page.screenshot({ path: 'eta-review-page.png', fullPage: true });
        console.log('📸 Review 截图: eta-review-page.png');

        const pageText = await page.locator('body').innerText();
        console.log('\n📄 页面内容（前 2000 字符）:');
        console.log(pageText.substring(0, 2000));

        const buttons = page.locator('input[type="submit"], input[type="button"], button');
        const btnCount = await buttons.count();
        console.log(`\n🔘 可用按钮: ${btnCount}`);
        for (let i = 0; i < btnCount; i++) {
            const val = await buttons.nth(i).getAttribute('value');
            console.log(`   - ${val}`);
        }

        console.log('\n⏸️  已暂停在 Review 页面。检查后按 Ctrl+C 退出。');
        await wait(5 * 60 * 1000);

    } catch (error) {
        console.error('\n❌ 错误:', error.message);
        await page.screenshot({ path: 'eta-error.png', fullPage: true });
        console.log('   错误截图: eta-error.png');
    } finally {
        await browser.close();
        console.log('\n🏁 完成');
    }
}

// === 辅助函数 ===

// Normalize input date to MM-DD-YYYY (accepts DD/MM/YYYY, DD-MM-YYYY, or MM-DD-YYYY)
function normalizeDateForEta(raw) {
    const v = String(raw || '').trim();
    if (!v) return v;

    // already MM-DD-YYYY
    if (/^\d{2}-\d{2}-\d{4}$/.test(v)) return v;

    // DD/MM/YYYY or DD-MM-YYYY -> MM-DD-YYYY
    const m = v.match(/^(\d{2})[/-](\d{2})[/-](\d{4})$/);
    if (m) {
        const dd = m[1];
        const mm = m[2];
        const yyyy = m[3];
        return `${mm}-${dd}-${yyyy}`;
    }
    return v;
}

// 设置 readonly 日期字段并触发完整事件链
async function setDateField(page, fieldId, value) {
    const normalized = normalizeDateForEta(value);
    await page.evaluate(({ id, val }) => {
        const el = document.getElementById(id);
        if (el) {
            el.focus();
            el.removeAttribute('readonly');
            el.value = val;
            el.setAttribute('readonly', '');
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('blur', { bubbles: true }));
        }
    }, { id: fieldId, val: normalized });
    await wait(500);
}

// 模拟真实键盘输入（用于 fill() 无效的字段）
async function typeInField(page, selector, value) {
    const el = page.locator(selector);
    await el.click();
    await wait(200);
    await page.keyboard.press('Meta+a');
    await page.keyboard.press('Backspace');
    await wait(100);
    await page.keyboard.type(value, { delay: 30 });
    await wait(200);
}

main().catch(console.error);
