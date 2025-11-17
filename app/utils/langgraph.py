# app/utils/langgraph.py

class StateGraph:
    def __init__(self):
        """
        Initialize the state graph. The state graph is a dictionary where the key is
        the state name (string) and the value is the state data (can be any object).
        """
        self.states = {}

    def add_state(self, state_name, state_data):
        """
        Adds a state to the graph.
        
        :param state_name: The name of the state (unique identifier).
        :param state_data: The data associated with this state (can be any object).
        """
        if state_name in self.states:
            raise ValueError(f"State with name '{state_name}' already exists.")
        self.states[state_name] = state_data

    def get_state(self, state_name):
        """
        Retrieves a state by its name.
        
        :param state_name: The name of the state to retrieve.
        :return: The data associated with the state, or None if the state doesn't exist.
        """
        return self.states.get(state_name, None)

    def update_state(self, state_name, new_state_data):
        """
        Updates the data of an existing state.
        
        :param state_name: The name of the state to update.
        :param new_state_data: The new data to associate with the state.
        """
        if state_name not in self.states:
            raise ValueError(f"State with name '{state_name}' does not exist.")
        self.states[state_name] = new_state_data

    def delete_state(self, state_name):
        """
        Deletes a state from the graph.
        
        :param state_name: The name of the state to delete.
        """
        if state_name in self.states:
            del self.states[state_name]
        else:
            raise ValueError(f"State with name '{state_name}' does not exist.")

    def get_all_states(self):
        """
        Returns all states in the graph.
        
        :return: A dictionary containing all states.
        """
        return self.states

    def __repr__(self):
        """
        Returns a string representation of the state graph for debugging purposes.
        """
        return f"StateGraph({self.states})"


# Example of how the StateGraph class can be used
if __name__ == "__main__":
    # Create a state graph
    graph = StateGraph()
    
    # Add some states
    graph.add_state("start", {"message": "Initial state"})
    graph.add_state("middle", {"message": "Middle state"})
    graph.add_state("end", {"message": "Final state"})
    
    # Retrieve and print states
    print(graph.get_state("start"))  # Output: {'message': 'Initial state'}
    print(graph.get_all_states())  # Output: {'start': {'message': 'Initial state'}, ...}
    
    # Update a state
    graph.update_state("start", {"message": "Updated start state"})
    print(graph.get_state("start"))  # Output: {'message': 'Updated start state'}
    
    # Delete a state
    graph.delete_state("middle")
    print(graph.get_all_states())  # Output: {'start': {...}, 'end': {...}}

    # Print the graph object (using __repr__)
    print(graph)  # Output: StateGraph({'start': {'message': 'Updated start state'}, 'end': {'message': 'Final state'}})
