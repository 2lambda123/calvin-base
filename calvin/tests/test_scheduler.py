import pytest
import unittest
from mock import Mock
from calvin.runtime.north import scheduler, calvinsys
from calvin.runtime.north.actormanager import ActorManager
from calvin.runtime.north.plugins.port import queue
from calvin.runtime.north.plugins.port.endpoint import LocalOutEndpoint, LocalInEndpoint
from calvin.csparser.codegen import calvin_codegen
        

def create_actor(kind, args):
    node = Mock()
    actor_manager = ActorManager(node)
    actor_id = actor_manager.new(kind, args)
    actor = actor_manager.actors[actor_id]
    actor._calvinsys = Mock()
    return actor

def app_from_script(script, script_name):
    deployable, issuetracker = calvin_codegen(script, script_name, verify=False)
    errors = issuetracker.errors(sort_key='reason')
    warnings = issuetracker.warnings(sort_key='reason')
    if errors:
        return {}, errors, warnings

    actors = {}
    for name, setup in deployable['actors'].iteritems():
        a_type = setup['actor_type']
        a_args = setup['args']
        a_args.update({"name":name}) # Optional, for human readability only
        a = create_actor(a_type, a_args)
        actors[name] = a

    for src, dests in deployable['connections'].iteritems():
        for dest in dests:
            a_name, p_name = src.split('.')
            outport = actors[a_name].outports[p_name]
            # FIXME: setup port properties (queue) from deployable info
            outport.set_queue(queue.fanout_fifo.FanoutFIFO({'queue_length': 4, 'direction': "out"}, {}))
            
            a_name, p_name = dest.split('.')
            inport = actors[a_name].inports[p_name]
            # FIXME: setup port properties (queue) from deployable info
            inport.set_queue(queue.fanout_fifo.FanoutFIFO({'queue_length': 4, 'direction': "in"}, {}))
            
            outport.attach_endpoint(LocalOutEndpoint(outport, inport))
            inport.attach_endpoint(LocalInEndpoint(inport, outport))
    
                
    return actors, errors, warnings
    

class TestBase(unittest.TestCase):

    def setUp(self):
        node = Mock()
        cs = calvinsys.get_calvinsys()
        cs.init(node)
        actor_manager = Mock()
        actor_manager.enabled_actors = Mock(return_value=[1, 3, 7])
        self.scheduler = scheduler.SimpleScheduler(node, actor_manager) 
        node.sched = self.scheduler

    def tearDown(self):
        pass

class SchedulerSanityCheck(TestBase):

    def test_sanity(self):
        assert self.scheduler.actor_mgr.enabled_actors() == [1, 3, 7]
        
class SchedulerCheckStrategy(TestBase):

    def test_simple(self):
        # Create actors
        src = create_actor('std.Constant', {"data":42, "name":"src"})
        filter = create_actor('std.Identity', {"name":"filter"})
        snk = create_actor('flow.Terminator', {"name":"snk"})
                    
        # Get get the ports
        src_outport = src.outports['token']
        filter_inport = filter.inports['token']  
        filter_outport = filter.outports['token']
        snk_inport = snk.inports['void']
        
        # Set the queue types and length for each port
        src_outport.set_queue(queue.fanout_fifo.FanoutFIFO({'queue_length': 4, 'direction': "out"}, {}))
        filter_inport.set_queue(queue.fanout_fifo.FanoutFIFO({'queue_length': 4, 'direction': "in"}, {}))
        filter_outport.set_queue(queue.fanout_fifo.FanoutFIFO({'queue_length': 4, 'direction': "out"}, {}))
        snk_inport.set_queue(queue.fanout_fifo.FanoutFIFO({'queue_length': 4, 'direction': "in"}, {}))
        
        # Create endpoints
        src_out_ep = LocalOutEndpoint(src_outport, filter_inport)
        filter_in_ep = LocalInEndpoint(filter_inport, src_outport)
        filter_out_ep = LocalOutEndpoint(filter_outport, snk_inport)
        snk_in_ep = LocalInEndpoint(snk_inport, filter_outport)
        
        # Attach the enpoints to the ports
        src_outport.attach_endpoint(src_out_ep)
        filter_inport.attach_endpoint(filter_in_ep)
        filter_outport.attach_endpoint(filter_out_ep)
        snk_inport.attach_endpoint(snk_in_ep)
                
        assert src.name == "src"    
        assert filter.name == "filter"          
        # Verify that src.token is connected to filter.token
        assert len(src.outports['token'].endpoints) == 1     
        assert src.outports['token'].endpoints[0].peer_port.owner.name == filter.name 
        assert src.outports['token'].endpoints[0].peer_port.owner == filter
        assert src.outports['token'].endpoints[0].peer_port.name == "token"
        assert src.outports['token'].endpoints[0].peer_port == filter.inports['token']
        
        # This is the same test as test_simple above, but using app_from_script to set up the application from a script. Much better in the long run. 
    def test_simple_script(self):
        script = """
        src : std.Constant(data=42)
        filter : std.Identity()
        snk : flow.Terminator()

        src.token > filter.token
        filter.token > snk.void
        """
        actors, errors, warnings = app_from_script(script, "test")
        
        assert not errors
        assert actors
        
        src = actors['test:src']
        filter = actors['test:filter']       
        skn = actors['test:snk']
        
        assert src.name == "test:src"    
        assert filter.name == "test:filter"          
        # Verify that src.token is connected to filter.token
        assert len(src.outports['token'].endpoints) == 1     
        assert src.outports['token'].endpoints[0].peer_port.owner.name == filter.name 
        assert src.outports['token'].endpoints[0].peer_port.owner == filter
        assert src.outports['token'].endpoints[0].peer_port.name == "token"
        assert src.outports['token'].endpoints[0].peer_port == filter.inports['token']

        
        