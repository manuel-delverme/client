import React from 'react';
import _ from 'lodash';
import {
  Button,
  Card,
  Dropdown,
  Grid,
  Icon,
  Segment,
  Modal,
} from 'semantic-ui-react';
import {panelClasses} from '../util/registry.js';
import QueryEditor from '../components/QueryEditor';
import {filterRuns, sortRuns} from '../util/runhelpers.js';
import withRunsDataLoader from '../containers/RunsDataLoader';
import ContentLoader from 'react-content-loader';
import Panel from '../components/Panel';

class EditablePanel extends React.Component {
  state = {editing: false};

  render() {
    return (
      <div>
        <Modal
          open={this.state.editing}
          dimmer={false}
          trigger={
            <Icon
              link
              name="edit"
              onClick={() => this.setState({editing: true})}
            />
          }>
          <Modal.Header>Edit Panel</Modal.Header>
          <Modal.Content style={{padding: 16}}>
            <Panel {...this.props} editMode={true} />
          </Modal.Content>
          <Modal.Actions>
            <Button
              floated="left"
              negative
              onClick={() => {
                this.props.removePanel(i);
                this.setState({editing: false});
              }}>
              <Icon name="trash" />Delete Chart
            </Button>
            <Button onClick={() => this.setState({editing: false})}>OK</Button>
          </Modal.Actions>
        </Modal>
        <Panel {...this.props} editMode={false} />
      </div>
    );
  }
}

export default withRunsDataLoader(EditablePanel);
