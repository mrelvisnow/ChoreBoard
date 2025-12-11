/**
 * Piano Tiles Game
 * Adapted from https://hyonktea.xyz/piano.html
 * Integrated into ChoreBoard arcade system
 */

class PianoGame {
    constructor(canvasId) {
        console.log('PianoGame constructor called with canvas ID:', canvasId);
        this.canvas = document.getElementById(canvasId);

        if (!this.canvas) {
            console.error('Canvas element not found with ID:', canvasId);
            throw new Error('Canvas element not found');
        }

        console.log('Canvas element found:', this.canvas);
        this.ctx = this.canvas.getContext('2d');

        if (!this.ctx) {
            console.error('Could not get 2D context from canvas');
            throw new Error('Could not get 2D context');
        }

        console.log('Canvas context obtained successfully');

        // Game state
        this.gameState = 'READY'; // READY, PLAYING, GAME_OVER
        this.score = 0;
        this.hardMode = false;

        // Tile configuration
        this.lanes = 4; // Q, W, O, P
        this.laneWidth = this.canvas.width / this.lanes;
        this.tiles = [];
        this.tileHeight = 100;

        // Speed progression: 2.0 → 10.2 tiles/sec
        this.baseSpeed = 2.0;
        this.maxSpeed = 10.2;
        this.currentSpeed = this.baseSpeed;

        // Input mapping
        this.keyMap = {
            'q': 0, 'Q': 0,
            'w': 1, 'W': 1,
            'o': 2, 'O': 2,
            'p': 3, 'P': 3
        };

        // Hard mode patterns (choreographed sequences)
        this.hardModePatterns = [
            [0, 1, 2, 3], // All lanes
            [0, 2, 0, 2], // Left-right alternating
            [1, 3, 1, 3], // Inner lanes alternating
            [0, 0, 1, 1, 2, 2, 3, 3], // Doubles
            [0, 1, 2, 3, 3, 2, 1, 0], // Wave
            [1, 2, 1, 2], // Center stairs
            [0, 3, 0, 3], // Outer lanes
            [1, 1, 2, 2, 3, 3], // Progressive doubles
        ];
        this.currentPattern = null;
        this.patternIndex = 0;

        // Animation
        this.lastFrameTime = 0;
        this.lastSpawnTime = 0;
        this.animationId = null;

        this.init();
    }

    init() {
        console.log('Initializing game...');
        this.setupInputHandlers();
        console.log('Input handlers setup complete');
        this.drawWelcomeScreen();
        console.log('Welcome screen drawn');
    }

    drawWelcomeScreen() {
        console.log('Drawing welcome screen...');
        console.log('Canvas size:', this.canvas.width, 'x', this.canvas.height);

        // Draw lanes
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

        // Draw "Press any key to start" text
        this.ctx.fillStyle = '#38bdf8'; // primary-400
        this.ctx.font = 'bold 24px Arial';
        this.ctx.textAlign = 'center';
        this.ctx.fillText('Press any key or tap to start', this.canvas.width / 2, this.canvas.height / 2);

        // Draw lane labels
        this.ctx.font = 'bold 48px Arial';
        const labels = ['Q', 'W', 'O', 'P'];
        labels.forEach((label, i) => {
            const x = (i + 0.5) * this.laneWidth;
            this.ctx.fillText(label, x, this.canvas.height - 50);
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
        hardModeToggle.addEventListener('change', (e) => {
            this.hardMode = e.target.checked;
        });
    }

    startGame() {
        this.gameState = 'PLAYING';
        this.score = 0;
        this.currentSpeed = this.baseSpeed;
        this.tiles = [];
        this.currentPattern = null;
        this.patternIndex = 0;

        // Hide hard mode toggle once game starts
        document.getElementById('hard-mode-container').style.display = 'none';

        // Start game loop
        this.lastFrameTime = performance.now();
        this.lastSpawnTime = this.lastFrameTime;
        this.gameLoop(this.lastFrameTime);
    }

    gameLoop(timestamp) {
        if (this.gameState !== 'PLAYING') return;

        const deltaTime = (timestamp - this.lastFrameTime) / 1000; // seconds
        this.lastFrameTime = timestamp;

        // Spawn tiles based on speed
        const spawnInterval = 1000 / this.currentSpeed; // ms
        if (timestamp - this.lastSpawnTime >= spawnInterval) {
            this.spawnTile();
            this.lastSpawnTime = timestamp;
        }

        this.update(deltaTime);
        this.render();

        this.animationId = requestAnimationFrame(this.gameLoop.bind(this));
    }

    spawnTile() {
        if (this.gameState !== 'PLAYING') return;

        let lane;

        if (this.hardMode && Math.random() < 0.3) {
            // Use choreographed pattern 30% of the time
            if (!this.currentPattern || this.patternIndex >= this.currentPattern.length) {
                // Pick new pattern
                this.currentPattern = this.hardModePatterns[
                    Math.floor(Math.random() * this.hardModePatterns.length)
                ];
                this.patternIndex = 0;
            }
            lane = this.currentPattern[this.patternIndex];
            this.patternIndex++;
        } else {
            // Random lane
            lane = Math.floor(Math.random() * this.lanes);
        }

        this.tiles.push({
            lane: lane,
            y: -this.tileHeight,
            hit: false
        });
    }

    update(deltaTime) {
        // Speed progression: exponential curve
        // Formula: speed = base + (max - base) * (1 - e^(-score / 50))
        const speedRange = this.maxSpeed - this.baseSpeed;
        const decayFactor = 50;
        this.currentSpeed = this.baseSpeed + speedRange * (1 - Math.exp(-this.score / decayFactor));

        const pixelsPerSecond = 150; // Constant visual speed

        // Update tile positions
        for (let i = this.tiles.length - 1; i >= 0; i--) {
            const tile = this.tiles[i];

            if (!tile.hit) {
                tile.y += pixelsPerSecond * deltaTime;

                // Check if tile missed (reached bottom)
                if (tile.y > this.canvas.height) {
                    this.gameOver();
                    return;
                }
            } else {
                // Continue moving hit tiles
                tile.y += pixelsPerSecond * deltaTime;

                // Remove hit tiles that are off screen
                if (tile.y > this.canvas.height + this.tileHeight) {
                    this.tiles.splice(i, 1);
                }
            }
        }
    }

    render() {
        // Clear canvas
        this.ctx.fillStyle = '#000';
        this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

        // Draw lanes (alternating colors)
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

        // Draw hit zone (bottom area)
        const hitZoneY = this.canvas.height - 150;
        this.ctx.fillStyle = 'rgba(56, 189, 248, 0.1)'; // primary-400 with transparency
        this.ctx.fillRect(0, hitZoneY, this.canvas.width, 150);

        // Draw tiles
        for (const tile of this.tiles) {
            const x = tile.lane * this.laneWidth;

            if (tile.hit) {
                this.ctx.fillStyle = 'rgba(34, 197, 94, 0.4)'; // green flash (fading)
            } else {
                // Gradient fill
                const gradient = this.ctx.createLinearGradient(x, tile.y, x, tile.y + this.tileHeight);
                gradient.addColorStop(0, '#8b5cf6'); // purple-500
                gradient.addColorStop(1, '#6d28d9'); // purple-700
                this.ctx.fillStyle = gradient;
            }

            // Draw tile with rounded corners
            this.roundRect(
                x + 4,
                tile.y,
                this.laneWidth - 8,
                this.tileHeight,
                8
            );
        }

        // Update score display
        document.getElementById('score-display').textContent = this.score;
    }

    roundRect(x, y, width, height, radius) {
        this.ctx.beginPath();
        this.ctx.moveTo(x + radius, y);
        this.ctx.lineTo(x + width - radius, y);
        this.ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
        this.ctx.lineTo(x + width, y + height - radius);
        this.ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
        this.ctx.lineTo(x + radius, y + height);
        this.ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
        this.ctx.lineTo(x, y + radius);
        this.ctx.quadraticCurveTo(x, y, x + radius, y);
        this.ctx.closePath();
        this.ctx.fill();
    }

    hitLane(lane) {
        // Find the first unhit tile in this lane within hit zone
        const hitZoneTop = this.canvas.height - 200;

        for (let i = 0; i < this.tiles.length; i++) {
            const tile = this.tiles[i];

            if (tile.lane === lane && !tile.hit && tile.y >= hitZoneTop && tile.y <= this.canvas.height) {
                // Hit!
                tile.hit = true;
                this.score++;

                // Visual feedback
                this.flashLane(lane);
                return;
            }
        }

        // Wrong hit - could add penalty here if desired
    }

    flashLane(lane) {
        // Brief visual feedback for successful hit
        const x = lane * this.laneWidth;
        this.ctx.fillStyle = 'rgba(34, 197, 94, 0.4)'; // green flash
        this.ctx.fillRect(x, this.canvas.height - 150, this.laneWidth, 150);
    }

    gameOver() {
        this.gameState = 'GAME_OVER';
        cancelAnimationFrame(this.animationId);

        // Show game over screen
        document.getElementById('final-score').textContent = this.score;
        document.getElementById('game-over-screen').classList.remove('hidden');
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
            document.getElementById('hard-mode-container').style.display = 'block';
            game.drawWelcomeScreen();
            game.gameState = 'READY';
        });
    }
});
