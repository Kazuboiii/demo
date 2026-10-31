const {chromium}=require('C:/Users/Kazuboiii/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'); const path=require('path');
(async()=>{
 const run=JSON.parse(fs.readFileSync('.runtime/qr-demo-accounts.json','utf8'));
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const errors=[];const scans=[];
 async function login(email,password){const context=await browser.newContext();const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));await page.goto('http://localhost:3000/login');await page.getByLabel('Work email').fill(email);await page.getByLabel('Password',{exact:true}).fill(password);await page.getByRole('button',{name:'Sign in',exact:true}).click();await page.waitForURL('**/dashboard');await page.goto('http://localhost:3000/qr-attendance');await page.getByLabel('Scan QR image').waitFor();return page;}
 const admin=await login('super@buildakar.com','admin123');
 const pages=await Promise.all(run.accounts.map(account=>login(account.email,run.password)));
 await admin.getByLabel('Business unit',{exact:true}).selectOption(String(run.business_unit));
 await admin.getByRole('button',{name:'Show staff QR display'}).click();
 // Wait for a newly rotated token so all five scans have a full validity window.
 let current=await admin.locator('code').textContent();
 await admin.waitForFunction(old=>document.querySelector('code')?.textContent!==old,current,{timeout:40000});
 await admin.locator('canvas').screenshot({path:path.resolve('.runtime/shared-workplace-qr.png')});
 await admin.screenshot({path:path.resolve('.runtime/staff-qr-display.png'),fullPage:true});
 await Promise.all(pages.map(async(page,i)=>{
   const responsePromise=page.waitForResponse(r=>r.url().includes('/rotating-qr/verify') && r.status() !== 308 && r.status() !== 307);
   await page.getByLabel('Scan QR image').setInputFiles(path.resolve('.runtime/shared-workplace-qr.png'));
   const response=await responsePromise;const data=await response.json();
   await page.getByRole('status').filter({hasText:'Attendance recorded.'}).waitFor();
   await page.screenshot({path:path.resolve('.runtime',`scan-user-${i+1}.png`),fullPage:true});
   scans.push({staff:run.accounts[i].name,status:response.status(),employee:data.event?.employee,event:data.event?.id,source:data.event?.source});
 }));
 fs.writeFileSync('.runtime/five-user-scans.json',JSON.stringify({scans,errors},null,2));
 console.log(JSON.stringify({scans,errors},null,2));
 if(scans.length!==5 || scans.some(s=>s.status!==200) || errors.length)throw Error('Scan verification failed');
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
