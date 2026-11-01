// node dev/check_theme.js http://host:8099 - theme sync checks against the harness
const { chromium } = require("playwright-core");

(async () => {
  const base = process.argv[2];
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox", "--disable-gpu", "--no-zygote", "--no-proxy-server"],
  });
  let failed = 0;
  const check = (ok, name) => { console.log(`${ok ? "ok  " : "FAIL"} ${name}`); failed += !ok; };
  const style = (frame, selector, property) => frame.evaluate(([s, p]) =>
    getComputedStyle(document.querySelector(s)).getPropertyValue(p).trim(), [selector, property]);

  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await page.goto(`${base}/harness?theme=dark#/`);
  const frame = page.frames()[1];
  await frame.waitForSelector(".tile:not(:has(.skeleton))");
  check(await style(frame, "body", "background-color") === "rgb(17, 17, 17)", "dark page background from the parent");
  check(await style(frame, ".card", "background-color") === "rgb(28, 28, 28)", "dark card background");
  check((await style(frame, "body", "font-family")).startsWith("Roboto"), "HA font family");
  const fonts = await frame.evaluate(async () => {
    await document.fonts.ready;
    return [...document.fonts].filter((f) => f.family.includes("Roboto") && f.status === "loaded").length;
  });
  check(fonts > 0, `Roboto copied into the frame and loaded (${fonts} faces)`);

  await page.evaluate(() => applyTheme("light"));
  await page.waitForTimeout(100);
  check(await style(frame, "body", "background-color") === "rgb(250, 250, 250)", "switch to light without a reload");
  check(await style(frame, ":root", "color-scheme") === "light", "color-scheme follows");

  await page.evaluate(() => applyTheme("custom"));
  await page.waitForTimeout(100);
  check(await style(frame, ".toolbar-tabs a.on", "color") === "rgb(123, 31, 162)", "custom primary color");
  check(await style(frame, ".card", "border-top-left-radius") === "20px", "custom card radius");
  check(await style(frame, ".toolbar", "border-bottom-style") === "none", "custom header border");
  await page.screenshot({ path: process.argv[3] || "custom.png" });

  await page.evaluate(() => applyTheme("dark"));
  await page.waitForTimeout(100);
  check(await style(frame, ".card", "border-top-left-radius") === "12px", "removed variables fall back");

  const direct = await browser.newContext({ colorScheme: "dark" });
  const standalone = await direct.newPage();
  await standalone.goto(`${base}/`);
  check(await style(standalone.mainFrame(), "body", "background-color") === "rgb(17, 17, 17)", "direct port: dark default");
  await standalone.emulateMedia({ colorScheme: "light" });
  check(await style(standalone.mainFrame(), "body", "background-color") === "rgb(250, 250, 250)", "direct port: light default");

  const errors = [];
  const tour = await direct.newPage();
  tour.on("pageerror", (error) => errors.push(error.message));
  tour.on("request", (request) => { if (!request.url().startsWith(base) && !request.url().startsWith("data:")) errors.push(`external: ${request.url()}`); });
  for (const hash of ["#/", "#/prints", "#/prints?status=error&sort=cost&dir=asc", "#/job/printer1:000015", "#/compare/printer1:000001/printer1:000021", "#/part/Clip", "#/preset/process/0.24mm%20Draft%20%40Creality%20K1C",
    "#/calibration", "#/maintenance", "#/analysis", "#/analysis?days=30", "#/projects", "#/project/1", "#/job/printer2:000006"]) {
    await tour.goto(`${base}/${hash}`);
    await tour.waitForSelector(".skeleton", { state: "detached" });
    await tour.waitForTimeout(80);
    check(!(await tour.textContent("#view")).includes("Не вдалося"), `page renders: ${hash}`);
  }
  check(errors.length === 0, `no script errors or external requests ${errors}`);
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch((error) => { console.error(error); process.exit(1); });
