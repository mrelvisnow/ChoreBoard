/**
 * Piano Tiles Game - New Implementation
 * Based on hyonktea.xyz/piano.html mechanics
 * Integrated into ChoreBoard arcade system
 */

class PianoGame {
    constructor(canvasId) {
        console.log('PianoGame constructor called');
        this.canvas = document.getElementById(canvasId);

        if (!this.canvas) {
            console.error('Canvas element not found');
            throw new Error('Canvas element not found');
        }

        // Set canvas to 80% of window height
        this.canvas.height = Math.floor(window.innerHeight * 0.8);
        console.log('Canvas height set to:', this.canvas.height);

        this.ctx = this.canvas.getContext('2d');

        if (!this.ctx) {
            console.error('Could not get 2D context');
            throw new Error('Could not get 2D context');
        }

        // Game constants
        this.lanes = 4; // Q, W, O, P
        this.laneWidth = this.canvas.width / this.lanes;
        this.tileHeight = Math.floor(this.canvas.height * 0.1); // 10% of canvas height

        // Speed constants
        this.BASE_TPS = 2.0;
        this.MAX_TPS = 10.2;
        this.EXTRA_TPS = this.MAX_TPS - this.BASE_TPS; // ~8.2
        this.SPEED_TAU = 250;

        // Game state
        this.gameState = 'READY'; // READY, PLAYING, GAME_OVER
        this.score = 0;
        this.hits = 0; // successful hits for speed calculation
        this.hardMode = false;
        this.currentTPS = this.BASE_TPS;

        // Tiles array
        this.tiles = [];

        // Last lane for jack probability
        this.lastLane = -1;

        // Pattern state
        this.currentPattern = null;
        this.patternIndex = 0;
        this.lastPatternGroup = null;

        // Input mapping
        this.keyMap = {
            'q': 0, 'Q': 0,
            'w': 1, 'W': 1,
            'o': 2, 'O': 2,
            'p': 3, 'P': 3
        };

        // Hard mode pattern groups
        this.PATTERN_GROUPS = {
            stairs: [
                [0,1,2,3], [3,2,1,0],
                [0,1,2,3,2,1,0],
                [1,2,3,2,1],
            ],
            trills: [
                [0,1,0], [1,0,1],
                [2,3,2], [3,2,3],
            ],
            runningMan: [
                [0,1,0,2,0,3,0,2,0,1,0,2,0,3,0,2,0,1],
                [3,2,3,1,3,0,3,1,3,2,3,1,3,0,3,1],
            ],
            rolls: [
                [0,1,2,3],
                [1,2,3,0],
                [2,3,0,1],
                [3,0,1,2],
            ],
            circles: [
                [1,0,2,3,0,1,3,2],
                [2,3,1,0,3,2,0,1],
            ],
            diamonds: [
                [1,3,0,2],
                [2,0,3,1],
                [1,3,0,2,2,0,3,1],
                [1,3,0,2,1,3,0,2],
                [2,0,3,1,2,0,3,1],
            ],
            gallops: [
                [2,3,1,2,0,1,3,0],
                [1,2,0,1,3,0,2,3],
                [0,1,3,0,2,3,1,2],
                [3,0,2,3,1,2,0,1],
                [0,3,1,0,2,1,3,2],
                [1,0,2,1,3,2,0,3],
                [2,1,3,2,0,3,1,0],
                [3,2,0,3,1,0,2,1],
            ],
            twohandtrills: [
                [0,2,0], [2,0,2],
                [1,3,1], [3,1,3],
                [0,3,0], [3,0,3],
            ],
            stackshifts: [
                [0,1,2,0,1,3,0,2,3,1,2,3],
                [3,2,1,3,2,0,3,1,0,2,1,0]
            ],
            rhombusman: [
                [0,1,0,2,0,3,1,3,2,3],
                [3,2,3,1,3,0,2,0,1,0]
            ],
            jack: [
                [0,0], [0,0,0], [0,0,0,0],
                [1,1], [1,1,1], [1,1,1,1],
                [2,2], [2,2,2], [2,2,2,2],
                [3,3], [3,3,3], [3,3,3,3]
            ]
        };

        // Animation
        this.lastFrameTime = 0;
        this.animationId = null;

        this.init();
    }

    init() {
        console.log('Initializing game...');
        this.setupInputHandlers();
        this.drawWelcomeScreen();
        console.log('Game ready');
    }

    drawWelcomeScreen() {
        // Clear canvas
        this.ctx.fillStyle = '#000';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw lane dividers
        this.ctx.strokeStyle = '#333';
        this.ctx.lineWidth = 4;
        for (let i = 1; i < this.lanes; i++) {
            const x = i * this.laneWidth;
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.canvas.height);
            this.ctx.stroke();
        }

        // Draw welcome text
        this.ctx.fillStyle = '#38bdf8';
        this.ctx.font = 'bold 24px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('Press any key or tap to start', this.canvas.width / 2, this.canvas.height / 2);

        // Draw lane labels
        this.ctx.font = 'bold 48px Arial';
        const labels = ['Q', 'W', 'O', 'P'];
        labels.forEach((label, i) => {
            const x = (i + 0.5) * this.laneWidth;
            this.ctx.fillText(label, x, this.canvas.height - 30);
        });
    }

    setupInputHandlers() {
        // Keyboard input
        document.addEventListener('keydown', (e) => {
            if (this.gameState === 'READY') {
                this.startGame();
                return;
            }

            if (this.gameState !== 'PLAYING') return;

            const lane = this.keyMap[e.key];
            if (lane !== undefined) {
                e.preventDefault();
                this.hitLane(lane);
            }
        });

        // Touch/mouse input on canvas
        this.canvas.addEventListener('click', (e) => {
            if (this.gameState === 'READY') {
                this.startGame();
                return;
            }

            if (this.gameState !== 'PLAYING') return;

            const rect = this.canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const scaleX = this.canvas.width / rect.width;
            const canvasX = x * scaleX;
            const lane = Math.floor(canvasX / this.laneWidth);

            if (lane >= 0 && lane < this.lanes) {
                this.hitLane(lane);
            }
        });

        // Hard mode toggle
        const hardModeToggle = document.getElementById('hard-mode-toggle');
        if (hardModeToggle) {
            hardModeToggle.addEventListener('change', (e) => {
                this.hardMode = e.target.checked;
            });
        }
    }

    startGame() {
        console.log('Starting game, hard mode:', this.hardMode);
        this.gameState = 'PLAYING';
        this.score = 0;
        this.hits = 0;
        this.currentTPS = this.BASE_TPS;
        this.tiles = [];
        this.lastLane = -1;
        this.currentPattern = null;
        this.patternIndex = 0;
        this.lastPatternGroup = null;

        // Hide hard mode toggle
        const hardModeContainer = document.getElementById('hard-mode-container');
        if (hardModeContainer) {
            hardModeContainer.style.display = 'none';
        }

        // Spawn initial tiles to fill screen from top, going upward
        // First tile at top of screen, rest spawn above it
        let spawnY = 0;
        while (spawnY > -this.canvas.height - this.tileHeight) {
            const lane = this.getNextLane();
            this.tiles.push({
                lane: lane,
                y: spawnY,
                hit: false,
                hitTime: 0
            });
            spawnY -= this.tileHeight; // Next tile spawns above
        }

        console.log('Initial tiles spawned:', this.tiles.length);

        // Start game loop
        this.lastFrameTime = performance.now();
        this.gameLoop(this.lastFrameTime);
    }

    calculateCurrentTPS() {
        // Base exponential formula
        let tps = this.BASE_TPS + this.EXTRA_TPS * (1 - Math.exp(-this.hits / this.SPEED_TAU));

        // Hard mode modifiers
        if (this.hardMode) {
            // Double the rate (half TAU)
            tps = this.BASE_TPS + this.EXTRA_TPS * (1 - Math.exp(-this.hits / (this.SPEED_TAU / 2)));

            // After reaching max, add 0.5 per 50 tiles
            if (tps >= this.MAX_TPS) {
                const tilesAfterMax = this.hits - (this.SPEED_TAU / 2) * Math.log(this.EXTRA_TPS / (this.EXTRA_TPS + 0.01));
                if (tilesAfterMax > 0) {
                    const bonus = Math.floor(tilesAfterMax / 50) * 0.5;
                    tps = this.MAX_TPS + bonus;
                }
            }
        } else {
            // Normal mode caps at MAX_TPS
            tps = Math.min(tps, this.MAX_TPS);
        }

        return tps;
    }

    getNextLane() {
        // Check if we're in a pattern
        if (this.currentPattern && this.patternIndex < this.currentPattern.length) {
            const lane = this.currentPattern[this.patternIndex];
            this.patternIndex++;

            // Pattern complete
            if (this.patternIndex >= this.currentPattern.length) {
                this.currentPattern = null;
                this.patternIndex = 0;
            }

            this.lastLane = lane;
            return lane;
        }

        // Hard mode: 50% chance to start a new pattern when not in one
        if (this.hardMode && Math.random() < 0.5) {
            this.selectNewPattern();
            if (this.currentPattern) {
                const lane = this.currentPattern[0];
                this.patternIndex = 1;
                this.lastLane = lane;
                return lane;
            }
        }

        // Random selection with 28% jack probability
        let lane;
        if (this.lastLane >= 0 && Math.random() < 0.28) {
            // Jack: same lane
            lane = this.lastLane;
        } else {
            // Random lane
            lane = Math.floor(Math.random() * this.lanes);
        }

        this.lastLane = lane;
        return lane;
    }

    selectNewPattern() {
        const groupNames = Object.keys(this.PATTERN_GROUPS);
        let selectedGroup;

        // Slight bias to repeat last pattern group (60% if last group exists)
        if (this.lastPatternGroup && Math.random() < 0.6) {
            selectedGroup = this.lastPatternGroup;
        } else {
            selectedGroup = groupNames[Math.floor(Math.random() * groupNames.length)];
        }

        const patterns = this.PATTERN_GROUPS[selectedGroup];
        this.currentPattern = patterns[Math.floor(Math.random() * patterns.length)];
        this.patternIndex = 0;
        this.lastPatternGroup = selectedGroup;

        console.log('New pattern selected:', selectedGroup, this.currentPattern);
    }

    gameLoop(timestamp) {
        if (this.gameState !== 'PLAYING') return;

        const deltaTime = (timestamp - this.lastFrameTime) / 1000; // seconds
        this.lastFrameTime = timestamp;

        // Calculate current TPS and scroll speed
        this.currentTPS = this.calculateCurrentTPS();
        const scrollSpeed = this.currentTPS * this.tileHeight; // pixels per second

        this.update(deltaTime, scrollSpeed);
        this.render(timestamp);

        this.animationId = requestAnimationFrame(this.gameLoop.bind(this));
    }

    update(deltaTime, scrollSpeed) {
        // Move all tiles down
        for (let i = this.tiles.length - 1; i >= 0; i--) {
            const tile = this.tiles[i];
            tile.y += scrollSpeed * deltaTime;

            // Remove tiles that scrolled off bottom
            if (tile.y > this.canvas.height + this.tileHeight) {
                // Check if unhit tile reached bottom (game over)
                if (!tile.hit) {
                    console.log('Tile missed! Game over.');
                    this.gameOver();
                    return;
                }
                this.tiles.splice(i, 1);
            }
        }

        // Find the topmost tile (most negative Y or smallest Y if all positive)
        let topmostY = Infinity;
        for (const tile of this.tiles) {
            if (tile.y < topmostY) {
                topmostY = tile.y;
            }
        }

        // Spawn new tiles above the topmost tile as needed
        // Keep spawning tiles to maintain a buffer above the screen
        while (topmostY > -this.canvas.height - this.tileHeight) {
            const lane = this.getNextLane();
            const newY = topmostY - this.tileHeight;
            this.tiles.push({
                lane: lane,
                y: newY,
                hit: false,
                hitTime: 0
            });
            topmostY = newY;
        }
    }

    render(timestamp) {
        // Clear canvas
        this.ctx.fillStyle = '#000';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw lanes
        for (let i = 0; i < this.lanes; i++) {
            this.ctx.fillStyle = i % 2 === 0 ? '#111' : '#000';
            this.ctx.fillRect(i * this.laneWidth, 0, this.laneWidth, this.canvas.height);
        }

        // Draw lane dividers
        this.ctx.strokeStyle = '#333';
        this.ctx.lineWidth = 4;
        for (let i = 1; i < this.lanes; i++) {
            const x = i * this.laneWidth;
            this.ctx.beginPath();
            this.ctx.moveTo(x, 0);
            this.ctx.lineTo(x, this.canvas.height);
            this.ctx.stroke();
        }

        // Draw tiles
        for (const tile of this.tiles) {
            const x = tile.lane * this.laneWidth;

            if (tile.hit) {
                // Flash blue briefly (0.1 seconds)
                const timeSinceHit = (timestamp - tile.hitTime) / 1000;
                if (timeSinceHit < 0.1) {
                    this.ctx.fillStyle = '#3b82f6'; // blue-500
                    this.ctx.fillRect(x + 2, tile.y, this.laneWidth - 4, this.tileHeight);
                }
                // After flash, tile is invisible (will be removed in update)
            } else {
                // Draw unhit tile with gradient
                const gradient = this.ctx.createLinearGradient(x, tile.y, x, tile.y + this.tileHeight);
                gradient.addColorStop(0, '#8b5cf6'); // purple-500
                gradient.addColorStop(1, '#6d28d9'); // purple-700
                this.ctx.fillStyle = gradient;
                this.ctx.fillRect(x + 2, tile.y, this.laneWidth - 4, this.tileHeight);
            }
        }

        // Update score display
        const scoreDisplay = document.getElementById('score-display');
        if (scoreDisplay) {
            scoreDisplay.textContent = this.score;
        }
    }

    hitLane(lane) {
        // Find the lowest (highest Y value) unhit tile
        let lowestTile = null;
        let lowestY = -Infinity;

        for (const tile of this.tiles) {
            if (!tile.hit && tile.y > lowestY && tile.y < this.canvas.height) {
                lowestTile = tile;
                lowestY = tile.y;
            }
        }

        // Check if hit the correct tile
        if (lowestTile && lowestTile.lane === lane) {
            // Correct hit!
            lowestTile.hit = true;
            lowestTile.hitTime = performance.now();
            this.score++;
            this.hits++;
            console.log('Hit! Score:', this.score, 'TPS:', this.currentTPS.toFixed(2));
        } else {
            // Wrong lane or no tile - game over
            console.log('Wrong hit! Expected lane:', lowestTile ? lowestTile.lane : 'none', 'Got:', lane);
            this.gameOver();
        }
    }

    gameOver() {
        console.log('Game over! Final score:', this.score);
        this.gameState = 'GAME_OVER';
        cancelAnimationFrame(this.animationId);

        // Show game over screen
        const finalScoreEl = document.getElementById('final-score');
        const gameOverScreen = document.getElementById('game-over-screen');

        if (finalScoreEl) {
            finalScoreEl.textContent = this.score;
        }
        if (gameOverScreen) {
            gameOverScreen.classList.remove('hidden');
        }
    }

    submitScore(userId) {
        const formData = new FormData();
        formData.append('user_id', userId);
        formData.append('score', this.score);
        formData.append('hard_mode', this.hardMode);

        // Add CSRF token
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        if (csrfToken) {
            formData.append('csrfmiddlewaretoken', csrfToken);
        }

        fetch('/piano/submit/', {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.location.href = data.redirect;
            } else {
                alert('Error: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Failed to submit score');
        });
    }
}

// Initialize game when page loads
document.addEventListener('DOMContentLoaded', function() {
    console.log('Piano game script loaded');

    const canvas = document.getElementById('piano-canvas');
    if (!canvas) {
        console.error('Canvas element not found!');
        return;
    }

    console.log('Canvas found, initializing game...');
    const game = new PianoGame('piano-canvas');
    console.log('Game initialized');

    // Submit score button
    const submitBtn = document.getElementById('submit-score-btn');
    if (submitBtn) {
        submitBtn.addEventListener('click', function() {
            const userId = document.getElementById('user-select').value;
            if (!userId) {
                alert('Please select your name');
                return;
            }
            game.submitScore(userId);
        });
    }

    // Play again button
    const playAgainBtn = document.getElementById('play-again-btn');
    if (playAgainBtn) {
        playAgainBtn.addEventListener('click', function() {
            document.getElementById('game-over-screen').classList.add('hidden');
            const hardModeContainer = document.getElementById('hard-mode-container');
            if (hardModeContainer) {
                hardModeContainer.style.display = 'block';
            }
            game.drawWelcomeScreen();
            game.gameState = 'READY';
        });
    }
});
