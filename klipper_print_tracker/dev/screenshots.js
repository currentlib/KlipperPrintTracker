// node dev/screenshots.js http://host:8099 out/dir [http://host:8098 for the empty database]
// Needs playwright-core, CHROMIUM_PATH can point at a browser.
const { chromium } = require("playwright-core");

const SIZES = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } };
const PAGES = {
  home: "#/", prints: "#/prints", job: "#/job/printer1:000015", compare: "#/compare/printer1:000001/printer1:000021",
  calibration: "#/calibration", maintenance: "#/maintenance", analysis: "#/analysis", projects: "#/projects", project: "#/project/1",
};

(async () => {
  const [base, out, emptyBase] = process.argv.slice(2);
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ["--no-sandbox", "--disable-gpu", "--no-zygote", "--no-proxy-server"],
  });
  const shots = [];
  for (const [size, viewport] of Object.entries(SIZES)) {
    for (const theme of ["dark", "light"]) {
      const context = await browser.newContext({ viewport, colorScheme: theme });
      const page = await context.newPage();
      const take = async (name, url) => {
        await page.goto("about:blank");
        await page.goto(url);
        const frame = page.frames()[1];
        await frame.waitForSelector(".skeleton", { state: "detached" });
        await page.waitForTimeout(150);
        const path = `${out}/${name}-${theme}-${size}.png`;
        await page.screenshot({ path });
        shots.push(path);
      };
      for (const [name, hash] of Object.entries(PAGES)) await take(name, `${base}/harness?theme=${theme}${hash}`);
      if (emptyBase) await take("empty", `${emptyBase}/harness?theme=${theme}#/`);
      await context.close();
    }
  }
  await browser.close();
  console.log(`${shots.length} screenshots in ${out}`);
})().catch((error) => { console.error(error); process.exit(1); });
