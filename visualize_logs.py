import matplotlib.pyplot as plt

# Create figure and axis
fig, ax1 = plt.subplots()

# Data for scores
score_x_data = []
score_y_data = []

# Data for temperature
temp_x_data = []
temp_y_data = []

# Plot for scores (primary y-axis)
score_line, = ax1.plot([], [], 'b-', label='Score')
ax1.set_xlabel('Log Entry')
ax1.set_ylabel('Score', color='b')
ax1.tick_params(axis='y', labelcolor='b')

# Create secondary y-axis for temperature
ax2 = ax1.twinx()
temp_line, = ax2.plot([], [], 'r-', label='Temperature')
ax2.set_ylabel('Temperature', color='r')
ax2.tick_params(axis='y', labelcolor='r')

# Title and grid
ax1.set_title('Simulated Annealing: Score and Temperature')
ax1.grid(True)

# Enable interactive mode
plt.ion()
plt.show(block=False)


def reset(instance_name=""):
    """Start a fresh graph for a new run and put the instance file name in the
    title, so each saved graph is clearly attributed to its instance."""
    global score_x_data, score_y_data, temp_x_data, temp_y_data
    score_x_data = []
    score_y_data = []
    temp_x_data = []
    temp_y_data = []

    score_line.set_data([], [])
    temp_line.set_data([], [])

    title = "Simulated Annealing: Score and Temperature"
    if instance_name:
        title += f"\nInstance: {instance_name}"
    ax1.set_title(title)

    ax1.relim()
    ax1.autoscale_view()
    ax2.relim()
    ax2.autoscale_view()
    fig.canvas.draw_idle()


def update(score, temperature, file=None):
    """Update the plot with new score and temperature values."""
    global score_x_data, score_y_data, temp_x_data, temp_y_data
    
    # Add new data points
    new_x = len(score_x_data) + 1
    score_x_data.append(new_x)
    score_y_data.append(score)
    temp_x_data.append(new_x)
    temp_y_data.append(temperature)
    
    # Update plot data
    score_line.set_data(score_x_data, score_y_data)
    temp_line.set_data(temp_x_data, temp_y_data)
    
    # Adjust axis limits
    ax1.relim()
    ax1.autoscale_view()
    ax2.relim()
    ax2.autoscale_view()
    
    # Redraw
    fig.canvas.draw()
    fig.canvas.flush_events()

    # Persist the current figure to disk if a target file was given.
    if file is not None:
        fig.savefig(file)

