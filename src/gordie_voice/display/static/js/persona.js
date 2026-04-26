/**
 * Gordie Persona — client-side state management, animations, and touch support.
 * Connects to the Flask-SocketIO backend to receive state updates.
 */

const socket = io();
const body = document.body;
const voiceView = document.getElementById('voice-view');
const promptView = document.getElementById('prompt-view');
const stateLabel = document.getElementById('state-label');
const waveformCanvas = document.getElementById('waveform');
const responseArea = document.getElementById('response-area');
const promptForm = document.getElementById('prompt-form');
const promptInput = document.getElementById('prompt-input');

const lockMode = window.GORDIE_LOCK_MODE || '';
const isTouch = window.GORDIE_TOUCH || false;

// All element refs declared up front to avoid TDZ issues
const recordOpinionBtnEl = document.getElementById('record-opinion-btn');
const fcStepEl = document.getElementById('opinion-fact-check');
const fcStatusTextEl = document.getElementById('fc-status-text');
const fcTranscriptEl = document.getElementById('fc-transcript');
const fcTranscriptTextEl = document.getElementById('fc-transcript-text');
const fcClaimsEl = document.getElementById('fc-claims');
const fcVerdictEl = document.getElementById('fc-verdict');
const fcVerdictEmojiEl = document.getElementById('fc-verdict-emoji');
const fcMeterFillEl = document.getElementById('fc-meter-fill');
const fcVerdictScoreEl = document.getElementById('fc-verdict-score');
const fcVerdictLabelEl = document.getElementById('fc-verdict-label');
const fcSummaryEl = document.getElementById('fc-summary');
const fcDoneBtnEl = document.getElementById('fc-done-btn');

const STATE_LABELS = {
    idle: 'Ready',
    listening: 'Listening...',
    transcribing: 'Processing...',
    querying: 'Thinking...',
    speaking: 'Speaking',
    registering: 'Registering...',
    error: 'Something went wrong',
};

// ---- View switching ----

function setActiveView(viewMode) {
    if (viewMode === 'voice') {
        voiceView.classList.add('active');
        promptView.classList.remove('active');
    } else {
        voiceView.classList.remove('active');
        promptView.classList.add('active');
        if (!isTouch) promptInput.focus();
    }
}

if (lockMode) {
    setActiveView(lockMode);
}

// ---- State management ----

socket.on('state', (data) => {
    const { state, mode } = data;
    body.dataset.state = state;
    body.dataset.mode = mode;
    stateLabel.textContent = STATE_LABELS[state] || state;

    if (!lockMode) {
        setActiveView(mode);
    }

    // Keep QR 10 more seconds when new user starts talking
    if (state === 'listening' && sessionQr && !sessionQr.classList.contains('hidden')) {
        if (sessionQrTimeout) clearTimeout(sessionQrTimeout);
        sessionQrTimeout = setTimeout(() => {
            sessionQr.classList.add('hidden');
            sessionQr.classList.remove('fade-in');
        }, 10000);
    }
});

// ---- Prompt submission ----

function submitPrompt(text) {
    text = text.trim();
    if (!text) return;
    responseArea.textContent = '';
    socket.emit('prompt_submit', { text });
    promptInput.value = '';
}

promptForm.addEventListener('submit', (e) => {
    e.preventDefault();
    submitPrompt(promptInput.value);
});

socket.on('response_chunk', (data) => {
    responseArea.textContent += data.text;
    responseArea.scrollTop = responseArea.scrollHeight;
});

socket.on('response_done', () => {});

// ---- Suggestion chips (touch) ----

document.querySelectorAll('.chip').forEach((chip) => {
    chip.addEventListener('click', () => {
        const query = chip.dataset.query;
        if (query) submitPrompt(query);
    });
});

// ---- Tap-to-wake (touch alternative to wake word) ----

const tapToWake = document.getElementById('tap-to-wake');
const touchHint = document.getElementById('touch-hint');

if (tapToWake) {
    tapToWake.addEventListener('click', () => {
        if (body.dataset.state === 'idle') {
            socket.emit('tap_wake', {});
            if (touchHint) touchHint.classList.add('hidden');
        }
    });
}

// ---- Registration ----

const regSendBtn = document.getElementById('reg-send-code');
const regVerifyBtn = document.getElementById('reg-verify');
const regPhoneInput = document.getElementById('reg-phone');
const regPhoneKbInput = document.getElementById('reg-phone-kb');
const regCodeStep = document.getElementById('reg-code-step');
const regStatus = document.getElementById('reg-status');

let registrationPhone = '';

function getPhoneValue() {
    if (isTouch) return regPhoneInput.value.trim();
    return (regPhoneKbInput || regPhoneInput).value.trim();
}

if (regSendBtn) {
    regSendBtn.addEventListener('click', () => {
        registrationPhone = getPhoneValue();
        if (!registrationPhone) return;
        regStatus.textContent = 'Sending code...';
        socket.emit('register_phone', { phone: registrationPhone });
    });
}

if (regVerifyBtn) {
    regVerifyBtn.addEventListener('click', () => {
        const code = getCodeDigitsValue();
        if (code.length < 6) return;
        regStatus.textContent = 'Verifying...';
        socket.emit('verify_code', { phone: registrationPhone, code });
    });
}

socket.on('registration_status', (data) => {
    if (data.step === 'otp_sent') {
        if (data.success) {
            regCodeStep.classList.remove('hidden');
            regStatus.textContent = 'Code sent! Check your phone.';
            focusCodeDigit(0);
        } else {
            regStatus.textContent = 'Failed to send code. Please try again.';
        }
    } else if (data.step === 'verified') {
        if (data.success) {
            regStatus.textContent = 'Registered successfully!';
            regStatus.style.color = 'var(--success)';
            setTimeout(() => {
                document.getElementById('registration-panel').classList.add('hidden');
            }, 2000);
        } else {
            regStatus.textContent = 'Invalid code. Please try again.';
            clearCodeDigits();
        }
    }
});

// ---- Numpad logic ----

function setupNumpad(numpadId, targetInput, formatFn) {
    const numpad = document.getElementById(numpadId);
    if (!numpad) return;

    numpad.querySelectorAll('.numpad-key').forEach((key) => {
        key.addEventListener('click', (e) => {
            e.preventDefault();
            const val = key.dataset.key;

            if (val === 'clear') {
                targetInput.value = '';
            } else if (val === 'back') {
                const raw = targetInput.value.replace(/\D/g, '');
                targetInput.value = formatFn ? formatFn(raw.slice(0, -1)) : raw.slice(0, -1);
            } else {
                const raw = targetInput.value.replace(/\D/g, '') + val;
                targetInput.value = formatFn ? formatFn(raw) : raw;
            }

            // Haptic feedback if available
            if (navigator.vibrate) navigator.vibrate(15);
        });
    });
}

function formatPhone(digits) {
    if (digits.length === 0) return '';
    if (digits.length <= 3) return `(${digits}`;
    if (digits.length <= 6) return `(${digits.slice(0, 3)}) ${digits.slice(3)}`;
    return `(${digits.slice(0, 3)}) ${digits.slice(3, 6)}-${digits.slice(6, 10)}`;
}

if (regPhoneInput) {
    setupNumpad('numpad-phone', regPhoneInput, formatPhone);
}

// ---- Code digit boxes ----

const codeDigits = document.querySelectorAll('.code-digit');

function focusCodeDigit(index) {
    if (index >= 0 && index < codeDigits.length) {
        codeDigits[index].focus();
    }
}

function getCodeDigitsValue() {
    return Array.from(codeDigits).map(d => d.value).join('');
}

function clearCodeDigits() {
    codeDigits.forEach(d => {
        d.value = '';
        d.classList.remove('filled');
    });
    focusCodeDigit(0);
}

// Keyboard input for code digits (non-touch)
codeDigits.forEach((digit, i) => {
    digit.addEventListener('input', () => {
        if (digit.value.length === 1) {
            digit.classList.add('filled');
            if (i < codeDigits.length - 1) focusCodeDigit(i + 1);
            // Auto-verify when all 6 entered
            if (getCodeDigitsValue().length === 6 && regVerifyBtn) {
                regVerifyBtn.click();
            }
        }
    });

    digit.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && !digit.value && i > 0) {
            focusCodeDigit(i - 1);
        }
    });
});

// Touch numpad for code digits
const codeNumpad = document.getElementById('numpad-code');
if (codeNumpad) {
    let codePosition = 0;

    codeNumpad.querySelectorAll('.numpad-key').forEach((key) => {
        key.addEventListener('click', (e) => {
            e.preventDefault();
            const val = key.dataset.key;

            if (val === 'clear') {
                clearCodeDigits();
                codePosition = 0;
            } else if (val === 'back') {
                if (codePosition > 0) {
                    codePosition--;
                    codeDigits[codePosition].value = '';
                    codeDigits[codePosition].classList.remove('filled');
                }
            } else if (codePosition < 6) {
                codeDigits[codePosition].value = val;
                codeDigits[codePosition].classList.add('filled');
                codePosition++;

                // Auto-verify when all 6 entered
                if (codePosition === 6 && regVerifyBtn) {
                    regVerifyBtn.click();
                }
            }

            if (navigator.vibrate) navigator.vibrate(15);
        });
    });
}

// ---- Waveform visualization ----

const wCtx = waveformCanvas.getContext('2d');
let waveAnimationId = null;

function drawWaveform() {
    if (body.dataset.state !== 'listening') {
        cancelAnimationFrame(waveAnimationId);
        wCtx.clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);
        return;
    }

    const w = waveformCanvas.width;
    const h = waveformCanvas.height;
    const t = Date.now() / 1000;

    wCtx.clearRect(0, 0, w, h);
    wCtx.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    wCtx.lineWidth = 2;
    wCtx.beginPath();

    for (let x = 0; x < w; x++) {
        const freq1 = Math.sin((x / w) * Math.PI * 4 + t * 3) * 15;
        const freq2 = Math.sin((x / w) * Math.PI * 7 + t * 5) * 8;
        const freq3 = Math.sin((x / w) * Math.PI * 2 + t * 1.5) * 12;
        const envelope = Math.sin((x / w) * Math.PI);
        const y = h / 2 + (freq1 + freq2 + freq3) * envelope;

        if (x === 0) wCtx.moveTo(x, y);
        else wCtx.lineTo(x, y);
    }

    wCtx.stroke();
    waveAnimationId = requestAnimationFrame(drawWaveform);
}

const observer = new MutationObserver(() => {
    if (body.dataset.state === 'listening') {
        drawWaveform();
    }
});
observer.observe(body, { attributes: true, attributeFilter: ['data-state'] });

// ---- Queue display ----

const queueDisplay = document.getElementById('queue-display');
const queueCurrentNumber = document.getElementById('queue-current-number');
const queueCurrentName = document.getElementById('queue-current-name');
const queueWaitingCount = document.getElementById('queue-waiting-count');
const queueWaitingList = document.getElementById('queue-waiting-list');

socket.on('queue_update', (data) => {
    if (!queueDisplay) return;

    queueDisplay.classList.remove('hidden');

    if (data.now_serving) {
        queueCurrentNumber.textContent = '#' + data.now_serving;
        queueCurrentName.textContent = data.now_serving_name || '';
    } else {
        queueCurrentNumber.textContent = '--';
        queueCurrentName.textContent = 'No one in queue';
    }

    queueWaitingCount.textContent = data.waiting_count || 0;

    // Render waiting tickets
    if (queueWaitingList) {
        queueWaitingList.textContent = '';
        (data.waiting_list || []).forEach((entry) => {
            const ticket = document.createElement('div');
            ticket.className = 'queue-ticket';
            ticket.textContent = '#' + entry.ticket_number;
            queueWaitingList.appendChild(ticket);
        });
    }
});

// ---- Payments ----

const paymentPanel = document.getElementById('payment-panel');
const payRecordingFee = document.getElementById('pay-recording-fee');
const payDonation = document.getElementById('pay-donation');
const payCommerce = document.getElementById('pay-commerce');
const paymentStatus = document.getElementById('payment-status');
const paymentStatusIcon = document.getElementById('payment-status-icon');
const paymentStatusMsg = document.getElementById('payment-status-msg');
const paymentCancelBtn = document.getElementById('payment-cancel-btn');

let paymentConfig = null;
let recordingFeeRequired = false;

function formatCurrency(cents, currency) {
    return new Intl.NumberFormat('en-CA', {
        style: 'currency',
        currency: currency || 'CAD',
    }).format(cents / 100);
}

socket.on('payment_config', (data) => {
    paymentConfig = data;
    if (!data.ready) return;

    let anyVisible = false;

    // Recording fee
    if (data.recording_fee.enabled) {
        recordingFeeRequired = true;
        const feeAmount = document.getElementById('recording-fee-amount');
        if (feeAmount) {
            feeAmount.textContent = formatCurrency(data.recording_fee.amount_cents, data.recording_fee.currency);
        }
        payRecordingFee.classList.remove('hidden');
        anyVisible = true;
    }

    // Donations
    if (data.donation.enabled) {
        const recipientEl = document.getElementById('donation-recipient');
        if (recipientEl) {
            let text = `Supporting ${data.donation.recipient}`;
            if (data.donation.charity_number) text += ` (Charity #${data.donation.charity_number})`;
            recipientEl.textContent = text;
        }

        const presetsEl = document.getElementById('donation-presets');
        if (presetsEl) {
            presetsEl.textContent = '';
            data.donation.presets_cents.forEach((cents) => {
                const btn = document.createElement('button');
                btn.className = 'donation-preset-btn';
                btn.textContent = formatCurrency(cents, 'CAD');
                btn.addEventListener('click', () => {
                    socket.emit('payment_donation', { amount_cents: cents });
                });
                presetsEl.appendChild(btn);
            });
        }

        if (data.donation.custom_allowed) {
            const customDiv = document.getElementById('donation-custom');
            if (customDiv) customDiv.classList.remove('hidden');
        }

        payDonation.classList.remove('hidden');
        anyVisible = true;
    }

    // Commerce
    if (data.commerce.enabled && data.commerce.catalog.length > 0) {
        const catalogEl = document.getElementById('commerce-catalog');
        if (catalogEl) {
            catalogEl.textContent = '';
            data.commerce.catalog.forEach((item) => {
                const card = document.createElement('button');
                card.className = 'commerce-item';

                const name = document.createElement('span');
                name.className = 'commerce-item-name';
                name.textContent = item.name;

                const price = document.createElement('span');
                price.className = 'commerce-item-price';
                price.textContent = formatCurrency(item.price_cents, 'CAD');

                card.appendChild(name);
                card.appendChild(price);
                card.addEventListener('click', () => {
                    socket.emit('payment_commerce', { items: [{ id: item.id, quantity: 1 }] });
                });
                catalogEl.appendChild(card);
            });
        }
        payCommerce.classList.remove('hidden');
        anyVisible = true;
    }

    if (anyVisible) paymentPanel.classList.remove('hidden');
});

// Custom donation submit
const donationCustomBtn = document.getElementById('donation-custom-btn');
const donationAmountInput = document.getElementById('donation-amount-input');
if (donationCustomBtn && donationAmountInput) {
    donationCustomBtn.addEventListener('click', () => {
        const dollars = parseFloat(donationAmountInput.value);
        if (!dollars || dollars < 1) return;
        const cents = Math.round(dollars * 100);
        socket.emit('payment_donation', { amount_cents: cents });
        donationAmountInput.value = '';
    });
}

// Recording fee button — pay first, then open recording
const payRecordBtn = document.getElementById('pay-record-btn');
if (payRecordBtn) {
    payRecordBtn.addEventListener('click', () => {
        socket.emit('payment_recording_fee');
    });
}

// Payment status updates
socket.on('payment_pending', (data) => {
    paymentStatusIcon.className = '';
    paymentStatusMsg.textContent = data.message || 'Tap or insert your card on the reader';
    paymentStatus.classList.remove('hidden');
});

socket.on('payment_result', (data) => {
    if (data.success) {
        paymentStatusIcon.className = 'success';
        paymentStatusMsg.textContent = 'Payment successful!';
        setTimeout(() => {
            paymentStatus.classList.add('hidden');
            // If this was a recording fee, open the opinion recorder
            if (data.type === 'recording_fee') {
                if (opinionOverlay) {
                    opinionOverlay.classList.remove('hidden');
                    showOpinionStep(opinionCategories);
                }
            }
        }, 1500);
    } else {
        paymentStatusIcon.className = 'failed';
        paymentStatusMsg.textContent = data.reason || 'Payment failed. Please try again.';
        setTimeout(() => { paymentStatus.classList.add('hidden'); }, 3000);
    }
});

socket.on('payment_cancelled', () => {
    paymentStatus.classList.add('hidden');
});

if (paymentCancelBtn) {
    paymentCancelBtn.addEventListener('click', () => {
        socket.emit('payment_cancel');
    });
}

// Override record opinion button — if fee is required, pay first
if (recordOpinionBtn) {
    const originalHandler = recordOpinionBtn.onclick;
    recordOpinionBtn.addEventListener('click', (e) => {
        if (recordingFeeRequired && paymentConfig && paymentConfig.recording_fee.enabled) {
            e.stopImmediatePropagation();
            socket.emit('payment_recording_fee');
        }
    }, true); // Capture phase to intercept before the existing handler
}

// ---- Device info / QR ----

const qrRiding = document.getElementById('qr-riding');

socket.on('device_info', (data) => {
    if (qrRiding && data.riding_name) {
        qrRiding.textContent = `Riding: ${data.riding_name}`;
    }
    // Show activation code if device not yet activated
    if (!data.activated && data.activation_code) {
        const label = document.getElementById('state-label');
        if (label) {
            label.textContent = `Activation code: ${data.activation_code}`;
        }
    }
});

// ---- Opinion Recording ----

const opinionOverlay = document.getElementById('opinion-overlay');
const opinionCategories = document.getElementById('opinion-categories');
const opinionRecording = document.getElementById('opinion-recording');
const opinionDone = document.getElementById('opinion-done');
const categoryGrid = document.getElementById('category-grid');
const cameraFeed = document.getElementById('camera-feed');
const recIndicator = document.getElementById('rec-indicator');
const countdownTime = document.getElementById('countdown-time');
const countdownBarFill = document.getElementById('countdown-bar-fill');
const opinionPromptText = document.getElementById('opinion-prompt-text');
const opinionStartBtn = document.getElementById('opinion-start-btn');
const opinionStopBtn = document.getElementById('opinion-stop-btn');
const opinionBackBtn = document.getElementById('opinion-back-btn');
const opinionCancelBtn = document.getElementById('opinion-cancel-btn');
const opinionDoneBtn = document.getElementById('opinion-done-btn');
const recordOpinionBtn = recordOpinionBtnEl;

let selectedCategory = null;
let recordingMaxSeconds = 30;
let isChallenge = false;
let challengeCategory = null;

const modeSelect = document.getElementById('opinion-mode-select');
const challengeCategories = document.getElementById('challenge-categories');
const challengeQuestionStep = document.getElementById('challenge-question-step');

// All steps that need to be toggled
const allOpinionSteps = [
    modeSelect, opinionCategories, challengeCategories,
    challengeQuestionStep, opinionRecording, opinionDone,
    fcStep,
].filter(Boolean);

function showOpinionStep(step) {
    allOpinionSteps.forEach(s => s.classList.add('hidden'));
    step.classList.remove('hidden');
}

// Open opinion overlay — start with mode selection
if (recordOpinionBtn) {
    recordOpinionBtn.addEventListener('click', () => {
        isChallenge = false;
        opinionOverlay.classList.remove('hidden');
        showOpinionStep(modeSelect);
    });
}

// Mode: Share Opinion
const modeOpinionBtn = document.getElementById('mode-opinion-btn');
if (modeOpinionBtn) {
    modeOpinionBtn.addEventListener('click', () => {
        isChallenge = false;
        showOpinionStep(opinionCategories);
    });
}

// Mode: Gordie Challenge
const modeChallengeBtn = document.getElementById('mode-challenge-btn');
if (modeChallengeBtn) {
    modeChallengeBtn.addEventListener('click', () => {
        isChallenge = true;
        showOpinionStep(challengeCategories);
    });
}

// Mode cancel
const modeCancelBtn = document.getElementById('mode-cancel-btn');
if (modeCancelBtn) {
    modeCancelBtn.addEventListener('click', () => {
        opinionOverlay.classList.add('hidden');
    });
}

// Populate categories from server using safe DOM methods
socket.on('opinion_categories', (data) => {
    if (!categoryGrid) return;
    categoryGrid.textContent = '';
    data.categories.forEach((cat) => {
        const card = document.createElement('button');
        card.className = 'category-card';

        const icon = document.createElement('span');
        icon.className = 'cat-icon';
        icon.textContent = cat.icon;

        const label = document.createElement('span');
        label.className = 'cat-label';
        label.textContent = cat.label;

        card.appendChild(icon);
        card.appendChild(label);

        card.addEventListener('click', () => {
            selectedCategory = cat;
            opinionPromptText.textContent = cat.prompt;
            showOpinionStep(opinionRecording);
            socket.emit('opinion_start_preview');
            cameraFeed.src = '/camera/feed';
        });
        categoryGrid.appendChild(card);
    });
});

// Start recording
if (opinionStartBtn) {
    opinionStartBtn.addEventListener('click', () => {
        if (!selectedCategory) return;
        socket.emit('opinion_start_recording', { category: selectedCategory.id });
    });
}

socket.on('opinion_recording_started', (data) => {
    recordingMaxSeconds = data.max_seconds || 30;
    opinionStartBtn.classList.add('hidden');
    opinionStopBtn.classList.remove('hidden');
    opinionBackBtn.classList.add('hidden');
    recIndicator.classList.remove('hidden');
});

// Countdown updates
socket.on('opinion_countdown', (data) => {
    const remaining = data.remaining_s;
    const elapsed = data.elapsed_s;
    const mins = Math.floor(remaining / 60);
    const secs = remaining % 60;
    countdownTime.textContent = `${mins}:${secs.toString().padStart(2, '0')}`;
    countdownBarFill.style.width = `${(elapsed / recordingMaxSeconds) * 100}%`;
    countdownTime.style.color = remaining <= 10 ? '#ef4444' : 'white';
});

// Stop recording
if (opinionStopBtn) {
    opinionStopBtn.addEventListener('click', () => {
        socket.emit('opinion_stop_recording');
    });
}

// Back to categories
if (opinionBackBtn) {
    opinionBackBtn.addEventListener('click', () => {
        socket.emit('opinion_cancel');
        cameraFeed.src = '';
        showOpinionStep(opinionCategories);
    });
}

// Cancel entirely
if (opinionCancelBtn) {
    opinionCancelBtn.addEventListener('click', () => {
        showOpinionStep(modeSelect);
    });
}

// Done — close overlay and reset
if (opinionDoneBtn) {
    opinionDoneBtn.addEventListener('click', () => {
        opinionOverlay.classList.add('hidden');
        opinionStartBtn.classList.remove('hidden');
        opinionStopBtn.classList.add('hidden');
        opinionBackBtn.classList.remove('hidden');
        countdownBarFill.style.width = '0%';
        countdownTime.textContent = '0:30';
        countdownTime.style.color = 'white';
        selectedCategory = null;
    });
}

// ---- Fact-check results ----

const fcStep = fcStepEl;
const fcStatusText = fcStatusTextEl;
const fcTranscript = fcTranscriptEl;
const fcTranscriptText = fcTranscriptTextEl;
const fcClaims = fcClaimsEl;
const fcVerdict = fcVerdictEl;
const fcVerdictEmoji = fcVerdictEmojiEl;
const fcMeterFill = fcMeterFillEl;
const fcVerdictScore = fcVerdictScoreEl;
const fcVerdictLabel = fcVerdictLabelEl;
const fcSummary = fcSummaryEl;
const fcDoneBtn = fcDoneBtnEl;

// Recording complete — show fact-check step if enabled
socket.on('opinion_recording_complete', (data) => {
    cameraFeed.src = '';
    recIndicator.classList.add('hidden');
    opinionStopBtn.classList.add('hidden');

    if (data.fact_check) {
        // Show fact-check step instead of done step
        fcClaims.textContent = '';
        fcTranscript.classList.add('hidden');
        fcVerdict.classList.add('hidden');
        fcDoneBtn.classList.add('hidden');
        fcStatusText.textContent = 'Transcribing your recording...';
        showOpinionStep(fcStep);
    } else {
        showOpinionStep(opinionDone);
    }
});

socket.on('fact_check_status', (data) => {
    if (data.step === 'transcribing') {
        fcStatusText.textContent = 'Transcribing your recording...';
    } else if (data.step === 'transcript_ready') {
        fcTranscriptText.textContent = data.transcript;
        fcTranscript.classList.remove('hidden');
        fcStatusText.textContent = 'Checking your facts against Canadian records...';
    } else if (data.step === 'checking') {
        fcStatusText.textContent = 'Fact-checking claims...';
    } else if (data.step === 'no_claims') {
        fcStatusText.textContent = 'No verifiable claims found — all opinion!';
        fcDoneBtn.classList.remove('hidden');
    } else if (data.step === 'error') {
        fcStatusText.textContent = data.message || 'Fact-check unavailable';
        fcDoneBtn.classList.remove('hidden');
    }
});

const VERDICT_LABELS = {
    true: 'True',
    mostly_true: 'Mostly True',
    mixed: 'Mixed',
    mostly_false: 'Mostly False',
    false: 'False',
    unverifiable: 'Unverifiable',
};

socket.on('fact_check_claim', (data) => {
    fcStatusText.textContent = `Checking claim ${data.index + 1} of ${data.total}...`;

    const card = document.createElement('div');
    card.className = 'fc-claim';
    card.dataset.verdict = data.verdict;

    const claimText = document.createElement('div');
    claimText.className = 'fc-claim-text';
    claimText.textContent = data.claim;
    card.appendChild(claimText);

    const verdict = document.createElement('span');
    verdict.className = 'fc-claim-verdict';
    verdict.textContent = VERDICT_LABELS[data.verdict] || data.verdict;
    card.appendChild(verdict);

    const explanation = document.createElement('div');
    explanation.className = 'fc-claim-explanation';
    explanation.textContent = data.explanation;
    card.appendChild(explanation);

    if (data.correction) {
        const correction = document.createElement('div');
        correction.className = 'fc-claim-correction';
        correction.textContent = data.correction;
        card.appendChild(correction);
    }

    fcClaims.appendChild(card);
});

socket.on('fact_check_complete', (data) => {
    fcStatusText.textContent = 'Fact-check complete!';

    // Reveal verdict with animation
    fcVerdictEmoji.textContent = data.verdict_emoji;
    fcVerdictScore.textContent = `${data.accuracy_pct}%`;
    fcVerdictLabel.textContent = data.verdict_label;
    fcSummary.textContent = data.summary;

    // Animate meter needle
    setTimeout(() => {
        const needle = fcMeterFill;
        if (needle) {
            needle.style.setProperty('--needle-pos', `${data.accuracy_pct}%`);
            const afterStyle = document.createElement('style');
            afterStyle.textContent = `#fc-meter-fill::after { left: ${data.accuracy_pct}% !important; }`;
            document.head.appendChild(afterStyle);
        }
    }, 100);

    fcVerdict.classList.remove('hidden');
    fcDoneBtn.classList.remove('hidden');
});

if (fcDoneBtn) {
    fcDoneBtn.addEventListener('click', () => {
        opinionOverlay.classList.add('hidden');
        // Reset all states
        opinionStartBtn.classList.remove('hidden');
        opinionStopBtn.classList.add('hidden');
        opinionBackBtn.classList.remove('hidden');
        countdownBarFill.style.width = '0%';
        countdownTime.textContent = '0:30';
        countdownTime.style.color = 'white';
        selectedCategory = null;
    });
}

// ---- Challenge mode ----

// Populate challenge category grid (reuses same categories from server)
socket.on('opinion_categories', (data) => {
    const grid = document.getElementById('challenge-category-grid');
    if (!grid) return;
    grid.textContent = '';
    data.categories.forEach((cat) => {
        if (cat.id === 'freeform') return; // Skip freeform for challenge
        const card = document.createElement('button');
        card.className = 'category-card';

        const icon = document.createElement('span');
        icon.className = 'cat-icon';
        icon.textContent = cat.icon;

        const label = document.createElement('span');
        label.className = 'cat-label';
        label.textContent = cat.label;

        card.appendChild(icon);
        card.appendChild(label);

        card.addEventListener('click', () => {
            challengeCategory = cat;
            socket.emit('challenge_start', { category: cat.id });
        });
        grid.appendChild(card);
    });
});

// Receive the challenge question
socket.on('challenge_question', (data) => {
    const questionText = document.getElementById('challenge-question-text');
    if (questionText) questionText.textContent = data.question;
    selectedCategory = challengeCategory;
    showOpinionStep(challengeQuestionStep);
});

// Ready to record challenge answer
const challengeReadyBtn = document.getElementById('challenge-ready-btn');
if (challengeReadyBtn) {
    challengeReadyBtn.addEventListener('click', () => {
        if (!selectedCategory) return;
        showOpinionStep(opinionRecording);
        socket.emit('opinion_start_preview');
        cameraFeed.src = '/camera/feed';
        // Auto-start recording after brief preview
        setTimeout(() => {
            socket.emit('opinion_start_recording', { category: selectedCategory.id });
        }, 1500);
    });
}

// Different question
const challengeBackBtn = document.getElementById('challenge-back-btn');
if (challengeBackBtn) {
    challengeBackBtn.addEventListener('click', () => {
        if (challengeCategory) {
            socket.emit('challenge_start', { category: challengeCategory.id });
        }
    });
}

// Challenge categories back button
const challengeCancelBtn = document.getElementById('challenge-cancel-btn');
if (challengeCancelBtn) {
    challengeCancelBtn.addEventListener('click', () => {
        showOpinionStep(modeSelect);
    });
}

// Voice-initiated recording (from follow-up conversation)
socket.on('opinion_voice_record_start', () => {
    isChallenge = false;
    opinionOverlay.classList.remove('hidden');
    showOpinionStep(modeSelect);
});

socket.on('opinion_error', (data) => {
    console.error('Opinion recording error:', data.message);
});

// ---- Session QR ----

const sessionQr = document.getElementById('session-qr');
const sessionQrImg = document.getElementById('session-qr-img');
let sessionQrTimeout = null;

socket.on('session_ended', (data) => {
    if (!data.session_id || !sessionQr || !sessionQrImg) return;
    sessionQrImg.src = '/qr/session/' + data.session_id;
    sessionQr.classList.remove('hidden');
    sessionQr.classList.add('fade-in');
    if (sessionQrTimeout) clearTimeout(sessionQrTimeout);
    sessionQrTimeout = setTimeout(() => {
        sessionQr.classList.add('hidden');
        sessionQr.classList.remove('fade-in');
    }, 30000);
});

// ---- Connection ----

socket.on('connect', () => {
    console.log('Connected to Gordie backend');
});
