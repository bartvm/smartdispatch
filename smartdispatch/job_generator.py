from __future__ import absolute_import

import os
import re
from smartdispatch.pbs import PBS
from smartdispatch import utils


def job_generator_factory(queue, commands, command_params={}, cluster_name=None, base_path="./"):
    if cluster_name == "guillimin":
        return GuilliminJobGenerator(queue, commands, command_params, base_path)
    elif cluster_name == "mammouth":
        return MammouthJobGenerator(queue, commands, command_params, base_path)
    elif cluster_name == "helios":
        return HeliosJobGenerator(queue, commands, command_params, base_path)
    elif cluster_name == "hades":
        return HadesJobGenerator(queue, commands, command_params, base_path)

    return JobGenerator(queue, commands, command_params, base_path)


class JobGenerator(object):

    """ Offers functionalities to generate PBS files for a given queue.

    Parameters
    ----------
    queue : `Queue` instance
        queue on which commands will be executed
    commands : list of str
        commands to put in PBS files
    command_params : dict
        information about the commands
    """

    def __init__(self, queue, commands, command_params={}, base_path="./"):
        self.commands = commands
        self.queue = queue
        self.job_log_filename = '"{base_path}/logs/job/"$PBS_JOBID".{{ext}}"'.format(base_path=base_path)

        self.nb_cores_per_command = command_params.get('nb_cores_per_command', 1)
        self.nb_gpus_per_command = command_params.get('nb_gpus_per_command', 1)
        #self.mem_per_command = command_params.get('mem_per_command', 0.0)

    def generate_pbs(self):
        """ Generates PBS files allowing the execution of every commands on the given queue. """
        nb_commands_per_node = self.queue.nb_cores_per_node // self.nb_cores_per_command

        if self.queue.nb_gpus_per_node > 0 and self.nb_gpus_per_command > 0:
            nb_commands_per_node = min(nb_commands_per_node, self.queue.nb_gpus_per_node // self.nb_gpus_per_command)

        pbs_files = []
        # Distribute equally the jobs among the PBS files and generate those files
        for i, commands in enumerate(utils.chunks(self.commands, n=nb_commands_per_node)):
            pbs = PBS(self.queue.name, self.queue.walltime)

            # TODO Move the add_options into the JobManager once created.
            pbs.add_options(o=self.job_log_filename.format(ext='out'), e=self.job_log_filename.format(ext='err'))

            # Set resource: nodes
            resource = "1:ppn={ppn}".format(ppn=len(commands) * self.nb_cores_per_command)
            if self.queue.nb_gpus_per_node > 0:
                resource += ":gpus={gpus}".format(gpus=len(commands) * self.nb_gpus_per_command)

            pbs.add_resources(nodes=resource)

            pbs.add_modules_to_load(*self.queue.modules)
            pbs.add_commands(*commands)

            pbs_files.append(pbs)

        return pbs_files

    def write_pbs_files(self, pbs_dir="./"):
        """ Writes PBS files allowing the execution of every commands on the given queue.

        Parameters
        ----------
        pbs_dir : str
            folder where to save pbs files
        """
        pbs_list = self.generate_pbs()
        pbs_filenames = []
        for i, pbs in enumerate(pbs_list):
            pbs_filename = os.path.join(pbs_dir, 'job_commands_' + str(i) + '.sh')
            pbs.save(pbs_filename)
            pbs_filenames.append(pbs_filename)

        return pbs_filenames

    def generate_pbs_with_account_name_from_env(self, environment_variable_name):
        pbs_list = JobGenerator.generate_pbs(self)

        if environment_variable_name not in os.environ:
            raise ValueError("Undefined environment variable: ${}. Please, provide your account name!".format(environment_variable_name))

        account_name = os.path.basename(os.path.realpath(os.getenv(environment_variable_name)))
        for pbs in pbs_list:
            pbs.add_options(A=account_name)

        return pbs_list

    def generate_pbs_with_account_name_from_file(self, rapid_filename):
        pbs_list = JobGenerator.generate_pbs(self)

        if not os.path.isfile(rapid_filename):
            raise ValueError("Account name file {} does not exist. Please, provide your account name!".format(rapid_filename))

        with open(rapid_filename, 'r') as rapid_file:
            account_name = rapid_file.read().strip()

        for pbs in pbs_list:
            pbs.add_options(A=account_name)

        return pbs_list


class MammouthJobGenerator(JobGenerator):

    def generate_pbs(self):
        pbs_list = super(MammouthJobGenerator, self).generate_pbs()

        if self.queue.name.endswith("@mp2"):
            for pbs in pbs_list:
                pbs.resources['nodes'] = re.sub("ppn=[0-9]+", "ppn=1", pbs.resources['nodes'])

        return pbs_list


class HadesJobGenerator(JobGenerator):

    def generate_pbs(self):
        pbs_list = super(HadesJobGenerator, self).generate_pbs()

        for pbs in pbs_list:
            gpus = re.match(".*gpus=([0-9]+)", pbs.resources['nodes']).group(1)
            pbs.resources['nodes'] = re.sub("ppn=[0-9]+", "ppn={}".format(gpus), pbs.resources['nodes'])
            pbs.resources['nodes'] = re.sub(":gpus=[0-9]+", "", pbs.resources['nodes'])

        return pbs_list


class GuilliminJobGenerator(JobGenerator):

    def generate_pbs(self):
        return self.generate_pbs_with_account_name_from_env('HOME_GROUP')


# https://wiki.calculquebec.ca/w/Ex%C3%A9cuter_une_t%C3%A2che#tab=tab6
class HeliosJobGenerator(JobGenerator):

    def generate_pbs(self):
        pbs_list = self.generate_pbs_with_account_name_from_file(os.path.join(os.environ['HOME'], ".default_rap"))

        for pbs in pbs_list:
            # Remove forbidden ppn option. Default is 2 cores per gpu.
            pbs.resources['nodes'] = re.sub(":ppn=[0-9]+", "", pbs.resources['nodes'])

        return pbs_list
