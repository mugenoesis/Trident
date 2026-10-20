// Browser check of Bambu printers (LAN / Developer mode) in Trident, against a *running* container. A fake Bambu printer (a small MQTT broker over
// TLS, in this process) is what the container talks to: it checks the access code, sends its status, answers "send everything" and records the
// pause, resume and stop it is told. Like smoke-test.mjs it needs Playwright's browsers (and openssl, for the fake printer's certificate):
//
//   docker run --rm --network host -v "$(pwd):/work" -w /work mcr.microsoft.com/playwright:v1.64.0-noble npm run smoke:bambu
//
// SMOKE_BASE_URL (default http://localhost:8000) says where Trident is. KLIPPER_FAKE_HOST is the address the container reaches this machine on
// (default 172.17.0.1, Docker's bridge gateway). The container may be on its first-run screen.

import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import tls from 'node:tls';
import { chromium } from 'playwright';

const BASE_URL = process.env.SMOKE_BASE_URL ?? 'http://localhost:8000';
const FAKE_HOST = process.env.KLIPPER_FAKE_HOST ?? '172.17.0.1';
const fail = (message) => {
	throw new Error(message);
};
const check = (condition, message) => {
	if (!condition) fail(message);
	console.log(`   ok: ${message}`);
};
const until = async (what, test, ms = 10000) => {
	const end = Date.now() + ms;
	while (Date.now() < end) {
		if (await test()) return true;
		await new Promise((r) => setTimeout(r, 200));
	}
	return fail(`timed out waiting for ${what}`);
};

// ---- a Bambu printer: MQTT 3.1.1 over TLS, as much of it as Trident uses ----
const SERIAL = '00M00A000000000';
const CODE = '12345678';
const printer = { state: 'RUNNING', percent: 25, told: [], commands: [], sockets: new Set(), uploads: {} };
// a second printer, with the camera of an A1 (a picture over TLS on port 6000), on the same broker
const A1_SERIAL = '03000A000000000';
const report = (serial = SERIAL) => ({
	print: {
		command: 'push_status',
		gcode_state: printer.state,
		subtask_name: 'benchy',
		mc_percent: printer.percent,
		mc_remaining_time: 90,
		layer_num: 12,
		total_layer_num: 80,
		nozzle_temper: 214.8,
		nozzle_target_temper: 215,
		bed_temper: 59.9,
		bed_target_temper: 60,
		chamber_temper: 31.4,
		print_error: 0,
		hms: [],
		sn: serial,
	},
});
const lengthBytes = (n) => {
	const out = [];
	let rest = n;
	do {
		let byte = rest % 128;
		rest = Math.floor(rest / 128);
		if (rest > 0) byte |= 128;
		out.push(byte);
	} while (rest > 0);
	return Buffer.from(out);
};
const packet = (first, body) => Buffer.concat([Buffer.from([first]), lengthBytes(body.length), body]);
const text = (s) => {
	const b = Buffer.from(s);
	const len = Buffer.alloc(2);
	len.writeUInt16BE(b.length);
	return Buffer.concat([len, b]);
};
const publishReport = (socket) => {
	for (const serial of socket.serials ?? []) {
		if (!socket.destroyed)
			socket.write(packet(0x30, Buffer.concat([text(`device/${serial}/report`), Buffer.from(JSON.stringify(report(serial)))])));
	}
};
function onConnect(socket, body) {
	let o = 2 + body.readUInt16BE(0) + 1; // the protocol name and level
	const connectFlags = body[o];
	o += 3; // the flags and the keep-alive
	o += 2 + body.readUInt16BE(o); // the client id
	let user = null;
	let pass = null;
	if (connectFlags & 0x80) {
		const l = body.readUInt16BE(o);
		user = body.toString('utf8', o + 2, o + 2 + l);
		o += 2 + l;
	}
	if (connectFlags & 0x40) pass = body.toString('utf8', o + 2, o + 2 + body.readUInt16BE(o));
	const ok = user === 'bblp' && pass === CODE;
	socket.write(packet(0x20, Buffer.from([0, ok ? 0 : 5])));
	if (!ok) socket.end();
}
function onSubscribe(socket, body) {
	let o = 2;
	let granted = Buffer.alloc(0);
	socket.serials ??= [];
	while (o < body.length) {
		const topic = body.toString('utf8', o + 2, o + 2 + body.readUInt16BE(o));
		socket.serials.push(topic.split('/')[1]); // device/<serial>/report
		o += 2 + body.readUInt16BE(o) + 1;
		granted = Buffer.concat([granted, Buffer.from([1])]);
	}
	socket.write(packet(0x90, Buffer.concat([body.slice(0, 2), granted])));
}
function onPublish(socket, flags, body) {
	const topicLength = body.readUInt16BE(0);
	const topic = body.toString('utf8', 2, 2 + topicLength);
	let o = 2 + topicLength;
	if ((flags >> 1) & 3) {
		socket.write(packet(0x40, body.slice(o, o + 2)));
		o += 2;
	}
	if (!topic.endsWith('/request')) return;
	const message = JSON.parse(body.slice(o).toString());
	if (message.pushing?.command === 'pushall') publishReport(socket);
	const command = message.print?.command;
	if (!command) return;
	printer.told.push(command);
	printer.commands.push(message.print);
	printer.state = { pause: 'PAUSE', resume: 'RUNNING', stop: 'IDLE' }[command] ?? printer.state;
	publishReport(socket);
}
const HANDLERS = {
	1: (socket, _flags, body) => onConnect(socket, body),
	3: (socket, flags, body) => onPublish(socket, flags, body),
	8: (socket, _flags, body) => onSubscribe(socket, body),
	12: (socket) => socket.write(Buffer.from([0xd0, 0])),
	14: (socket) => socket.end(),
};
const handle = (socket, type, flags, body) => HANDLERS[type]?.(socket, flags, body);
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'fake-bambu-'));
execFileSync(
	'openssl',
	[
		'req',
		'-x509',
		'-newkey',
		'rsa:2048',
		'-nodes',
		'-keyout',
		`${directory}/key.pem`,
		'-out',
		`${directory}/cert.pem`,
		'-subj',
		'/CN=fake-bambu',
		'-days',
		'1',
	],
	{
		stdio: 'ignore',
	},
);
const broker = tls.createServer(
	{ key: fs.readFileSync(`${directory}/key.pem`), cert: fs.readFileSync(`${directory}/cert.pem`) },
	(socket) => {
		printer.sockets.add(socket);
		socket.on('close', () => printer.sockets.delete(socket));
		socket.on('error', () => undefined);
		let pending = Buffer.alloc(0);
		socket.on('data', (chunk) => {
			pending = Buffer.concat([pending, chunk]);
			for (;;) {
				if (pending.length < 2) return;
				let length = 0;
				let o = 1;
				let multiplier = 1;
				let byte = 0;
				do {
					if (o >= pending.length) return;
					byte = pending[o++];
					length += (byte & 127) * multiplier;
					multiplier *= 128;
				} while (byte & 128);
				if (pending.length < o + length) return;
				handle(socket, pending[0] >> 4, pending[0] & 15, pending.slice(o, o + length));
				pending = pending.slice(o + length);
			}
		});
	},
);

// ---- the same printer's FTPS (implicit TLS on port 990): login, passive mode, and STOR ----
const tlsOptions = { key: fs.readFileSync(`${directory}/key.pem`), cert: fs.readFileSync(`${directory}/cert.pem`) };
const ftps = tls.createServer(tlsOptions, (control) => {
	control.on('error', () => undefined);
	const reply = (line) => control.write(`${line}\r\n`);
	let stored = null;
	let dataServer = null;
	let loggedIn = false;
	reply('220 Fake Bambu FTPS');
	const finishStore = (name, data) => {
		printer.uploads[name] = data;
		reply('226 Transfer complete');
	};
	const commands = {
		USER: () => reply('331 Password please'),
		PASS: (arg) => {
			loggedIn = arg === CODE;
			reply(loggedIn ? '230 Logged in' : '530 Login incorrect');
		},
		PBSZ: () => reply('200 PBSZ=0'),
		PROT: () => reply('200 Protection set to Private'),
		TYPE: () => reply('200 Type set'),
		PASV: () => {
			dataServer = tls.createServer(tlsOptions, (data) => {
				const chunks = [];
				data.on('error', () => undefined);
				data.on('data', (c) => chunks.push(c));
				data.on('end', () => {
					data.end();
					finishStore(stored, Buffer.concat(chunks));
				});
			});
			dataServer.listen(0, '0.0.0.0', () => {
				const port = dataServer.address().port;
				reply(`227 Entering Passive Mode (0,0,0,0,${port >> 8},${port & 255})`);
			});
		},
		STOR: (arg) => {
			stored = arg;
			reply(loggedIn ? '150 Ok to send data' : '530 Not logged in');
		},
		QUIT: () => {
			reply('221 Bye');
			control.end();
		},
	};
	let pending = '';
	control.on('data', (chunk) => {
		pending += chunk.toString();
		for (let at = pending.indexOf('\r\n'); at >= 0; at = pending.indexOf('\r\n')) {
			const line = pending.slice(0, at);
			pending = pending.slice(at + 2);
			const [word, ...rest] = line.split(' ');
			(commands[word.toUpperCase()] ?? (() => reply('502 Not implemented')))(rest.join(' '));
		}
	});
	control.on('close', () => dataServer?.close());
});
await new Promise((resolve) => ftps.listen(990, '0.0.0.0', resolve));

// ---- an A1's camera: after an 80-byte login, a picture behind a 16-byte header (TLS, port 6000) ----
const camera = { picture: null, logins: [] };
const cameraServer = tls.createServer(tlsOptions, (socket) => {
	socket.on('error', () => undefined);
	let got = Buffer.alloc(0);
	socket.on('data', (chunk) => {
		got = Buffer.concat([got, chunk]);
		if (got.length < 80 || !camera.picture) return;
		camera.logins.push(got.subarray(0, 80));
		const header = Buffer.alloc(16);
		header.writeUInt32LE(camera.picture.length, 0);
		socket.write(Buffer.concat([header, camera.picture]));
		got = Buffer.alloc(0);
	});
});
await new Promise((resolve) => cameraServer.listen(6000, '0.0.0.0', resolve));
await new Promise((resolve) => broker.listen(0, '0.0.0.0', resolve));
const address = `${FAKE_HOST}:${broker.address().port}`;
// a real printer pushes its status about every second while it works
const pusher = setInterval(() => {
	for (const s of printer.sockets) publishReport(s);
}, 1000);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 1500 } });
const pageErrors = [];
page.on('pageerror', (err) => pageErrors.push(String(err)));

console.log(`[1/9] Adding a Bambu printer (the fake one is at ${address}) ...`);
await page.goto(BASE_URL, { waitUntil: 'networkidle' });
const justMe = page.getByRole('button', { name: 'Just me (no login)' });
if (await justMe.isVisible().catch(() => false)) await justMe.click();
await page.waitForSelector('text=Trident Studio');
await page.getByLabel('Printer vendor').selectOption({ label: 'BBL' });
const machine = page.getByLabel(/^Printer \(nozzle/);
await machine.selectOption({ label: 'Bambu Lab X1 Carbon 0.4 nozzle' });
await page.getByRole('button', { name: 'Save current setup as printer…' }).click();
const form = page.locator('form.auth-form', { hasText: 'Save printer' });
await form.getByLabel('Name', { exact: true }).fill('X1C');
await form.getByLabel(/^Connection/).selectOption({ label: 'Bambu Lab (LAN mode)' });
check(await form.getByLabel('IP address').isVisible(), 'a Bambu connection asks for the printer’s IP address');
check(await form.getByLabel('Serial number').isVisible(), 'its serial number');
check(await form.getByLabel('Access code').isVisible(), 'and its access code');
check((await form.getByLabel(/HTTP username/).count()) === 0, 'and not the web-address fields of the other kinds');
await form.getByLabel('IP address').fill(address);
await form.getByLabel('Serial number').fill(SERIAL);

console.log('[2/9] Testing the connection ...');
await form.getByLabel('Access code').fill('wrong');
await form.getByRole('button', { name: 'Test connection' }).click();
await form.getByText(/refused the access code/).waitFor({ timeout: 15000 });
check(true, 'a wrong access code is said to be that');
await form.getByLabel('Access code').fill(CODE);
await form.getByRole('button', { name: 'Test connection' }).click();
await form.getByText(/Connected \(printer state: printing\)/).waitFor({ timeout: 15000 });
check(true, 'the right one connects, and says how the printer is');
await form.getByRole('button', { name: 'Save printer' }).click();
await page.getByText('Manage saved printers (1)').waitFor();
check(true, 'the printer is saved');

console.log('[3/9] Editing it ...');
await page.getByText('Manage saved printers (1)').click();
await page.getByRole('listitem').getByRole('button', { name: 'Settings', exact: true }).click();
const edit = page.locator('form.printer-settings-form');
check((await edit.getByLabel('IP address').inputValue()) === address, 'the address is shown');
check((await edit.getByLabel('Serial number').inputValue()) === SERIAL, 'and the serial number');
check((await edit.getByLabel(/^Access code/).inputValue()) === '', 'but never the access code');
check((await edit.getByText(/leave blank to keep/).count()) >= 1, 'which can be left blank to keep it');
await edit.getByRole('button', { name: 'Cancel' }).click();

console.log('[4/9] Watching it ...');
await page.getByRole('button', { name: 'Printers', exact: true }).click();
const panel = page.getByRole('dialog', { name: 'Your printers' });
await panel.waitFor();
const card = panel.locator('.printer-card', { hasText: 'X1C' });
await card.getByText('Printing', { exact: true }).waitFor({ timeout: 15000 });
check((await card.getByText('benchy').count()) === 1, 'the print is named');
check((await card.getByText('25%').count()) === 1, 'the progress is shown');
check((await card.getByText('layer 12 of 80').count()) === 1, 'and the layers');
check((await card.getByText(/1 h 30 min left/).count()) === 1, 'and the time left (it reports minutes)');
check((await card.getByText('214.8°').count()) === 1, 'the nozzle');
check((await card.getByText('Chamber').count()) === 1, 'and an X1’s chamber');

console.log('[5/9] Pausing, resuming and cancelling ...');
await card.getByRole('button', { name: 'Pause' }).click();
await until('the pause', () => printer.told.includes('pause'));
await card.getByText('Paused', { exact: true }).waitFor({ timeout: 15000 });
check(true, 'the printer was told to pause, and shows as paused');
await card.getByRole('button', { name: 'Resume' }).click();
await until('the resume', () => printer.told.includes('resume'));
await card.getByText('Printing', { exact: true }).waitFor({ timeout: 15000 });
check(true, 'and to resume');
await card.getByRole('button', { name: 'Cancel print…' }).click();
const confirm = page.getByRole('alertdialog', { name: /Cancel the print on X1C/ });
await confirm.waitFor();
await confirm.getByRole('button', { name: 'Cancel the print', exact: true }).click();
await until('the stop', () => printer.told.includes('stop'));
check(true, 'cancelling asks first, then sends the printer’s own stop');

console.log('[6/9] What the printer reports, for finding out what it says ...');
await card.getByText('Raw status', { exact: true }).click();
const raw = card.locator('pre.printer-raw');
await raw.waitFor({ timeout: 15000 });
const rawText = await raw.innerText();
check(rawText.includes('gcode_state'), 'the raw report is shown');
check(
	!rawText.includes(SERIAL) && !rawText.includes(CODE) && !rawText.includes(FAKE_HOST),
	'without the serial number, the code or the address',
);

console.log('[7/9] Sending a sliced print ...');
await panel.getByRole('button', { name: /Close/ }).click();
await page.locator('input[type="file"][data-model-input]').setInputFiles(path.resolve('fixtures/test-cube.stl'));
await page.waitForSelector('text=Ready to slice');
await page.getByLabel('Saved printer').selectOption({ label: 'X1C' });
await page.getByRole('button', { name: 'Slice', exact: true }).click();
const send = page.getByRole('button', { name: 'Send to X1C' });
await send.waitFor({ timeout: 120000 });
check(await page.getByLabel(/Print from the AMS/).isVisible(), 'a Bambu printer is offered the AMS');
await send.click();
await page.getByText('Sent to X1C.').waitFor({ timeout: 30000 });
const name = 'test-cube.gcode.3mf';
check(printer.uploads[name]?.length > 1000, 'the sliced 3MF is uploaded to the printer by FTPS');
check(printer.uploads[name].subarray(0, 2).toString() === 'PK', 'and it is a 3MF (a zip file)');
check(!printer.told.includes('project_file'), 'without being started unless asked');
await page.getByLabel(/Start printing immediately/).check();
await page.getByLabel(/Print from the AMS/).check();
await send.click();
await until('the start command', () => printer.told.includes('project_file'), 30000);
const start = printer.commands.find((c) => c.command === 'project_file');
check(start.file === name && start.url === `ftp:///${name}`, 'the print is started by name, as ftp:///name');
check(start.param === 'Metadata/plate_1.gcode', 'for the plate in the 3MF');
check(start.md5 === crypto.createHash('md5').update(printer.uploads[name]).digest('hex'), 'with the file\u2019s checksum');
check(start.use_ams === true && JSON.stringify(start.ams_mapping) === '[0]', 'from the AMS\u2019s first slot when asked');

console.log('[8/9] The cameras ...');
// a real JPEG, made by the browser
camera.picture = Buffer.from(
	await page.evaluate(() => {
		const canvas = document.createElement('canvas');
		canvas.width = 16;
		canvas.height = 9;
		const context = canvas.getContext('2d');
		context.fillStyle = 'rgb(20,160,40)';
		context.fillRect(0, 0, 16, 9);
		return canvas.toDataURL('image/jpeg').split(',')[1];
	}),
	'base64',
);
printer.state = 'RUNNING';
const saved = await page.evaluate(
	async ([host, serial, code]) => {
		const body = {
			name: 'A1',
			vendor: 'BBL',
			machine_profile: 'x',
			process_profile: 'x',
			host_type: 'bambu',
			print_host: host,
			device_id: serial,
			printhost_apikey: code,
		};
		const res = await fetch('/printers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
		return res.status;
	},
	[address, A1_SERIAL, CODE],
);
check(saved === 200, 'an A1 is saved too');
await page.getByRole('button', { name: 'Printers', exact: true }).click();
const again = page.getByRole('dialog', { name: 'Your printers' });
const a1 = again.locator('.printer-card').filter({ has: page.getByText('A1', { exact: true }) });
const picture = a1.locator('img.printer-cam');
await picture.waitFor({ timeout: 60000 });
check(await picture.evaluate((img) => img.complete && img.naturalWidth > 0), 'an A1’s camera picture is shown on its card');
check(
	camera.logins.length > 0 &&
		camera.logins[0].subarray(16, 20).toString() === 'bblp' &&
		camera.logins[0].subarray(48, 56).toString() === CODE,
	'it logged in to the camera as bblp with the access code',
);
const x1 = again.locator('.printer-card').filter({ has: page.getByText('X1C', { exact: true }) });
await x1.getByText(/camera is not answering/).waitFor({ timeout: 60000 });
check(!(await x1.innerText()).includes(CODE), 'an X1 whose stream cannot be opened says so, without the access code');

console.log('[9/9] A printer saved as monitor only ...');
await page.evaluate(
	async ([host, serial, code]) => {
		const body = {
			name: 'P1S',
			vendor: 'BBL',
			machine_profile: 'x',
			process_profile: 'x',
			host_type: 'bambu',
			print_host: host,
			device_id: serial,
			printhost_apikey: code,
			monitor_only: true,
		};
		await fetch('/printers', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
	},
	[address, A1_SERIAL, CODE],
);
await again.getByRole('button', { name: /Close/ }).click();
await page.getByRole('button', { name: 'Printers', exact: true }).click();
const p1s = page.getByRole('dialog', { name: 'Your printers' }).locator('.printer-card', { hasText: 'P1S' });
await p1s.getByText('Printing', { exact: true }).waitFor({ timeout: 30000 });
check((await p1s.getByText(/Monitor only/).count()) === 1, 'a monitor-only printer says it can only be watched');
check((await p1s.getByRole('button', { name: /Pause|Resume|Cancel/ }).count()) === 0, 'and has no buttons for the print');

check(pageErrors.length === 0, `no page errors (${pageErrors.join('; ')})`);
clearInterval(pusher);
for (const s of printer.sockets) s.destroy();
await browser.close();
broker.close();
ftps.close();
cameraServer.close();
console.log('bambu browser check passed');
