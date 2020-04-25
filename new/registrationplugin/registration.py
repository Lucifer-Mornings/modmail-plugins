from discord.ext import commands

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        print(message.content)

    @commands.command()
    async def say(self, ctx, *, message):
        await ctx.send(message)

def setup(bot):
    bot.add_cog(MyCog(bot))

import asyncio
import re
from datetime import datetime

from dateutil.relativedelta import relativedelta
from discord.ext import commands

from Checks.bot_checks import can_delete, can_embed, can_manage_user
from Formats.formats import avatar_check, pagify
from Functions.registration import *
from Lines.custom_emotes import CustomEmotes as Get_emote
from Functions.core import send_message


# For the Non-Premium Guilds, the non database logic
def role_validation(roles_to_validate, flags):
    role_ids = {}

    for role in (nsfw_sfw_roles if flags else sfw_roles):
        role_check = discord.utils.get(roles_to_validate, name=role)

        if role_check:
            role_ids[role_check.name] = role_check

    count = len(role_ids)

    if count < len(nsfw_sfw_roles):
        return False, role_ids
    else:
        return True, role_ids


class Registration(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_permissions(manage_roles=True)
    async def regroles(self, ctx):
        """Create the necessary roles for registration and save them"""
        guild = ctx.guild
        async with ctx.pool.acquire() as db:
            guild_data = await db.fetchrow(
                "SELECT registration_nsfw, registration_roles, registration_roles_setup,"
                "registration_enabled FROM botsettings_guild WHERE id = $1",
                guild.id
            )
        if not guild_data["registration_enabled"]:
            await ctx.send(
                "Registration needs to be enabled before you can use it. You can enable "
                "it in the dashboard at https://sheri.bot/settings"
            )
        elif not guild_data['registration_roles_setup']:
            def check(m):
                return m.channel == ctx.channel and m.author == ctx.author

            try:
                async with ctx.pool.acquire() as db:
                    nsfw = await ctx.pool.fetchval(
                        "SELECT registration_nsfw FROM botsettings_guild WHERE id = $1",
                        ctx.guild.id
                    )
                if nsfw:
                    instance = "with your NSFW Settings marked."
                    roles_to_add = nsfw_sfw_roles
                else:
                    instance = "with your SFW Settings marked."
                    roles_to_add = sfw_roles

                list_roles = ", ".join(roles_to_add)
                await ctx.send(
                    "This will create the roles needed for this service to function properly.\n"
                    f"The following roles that will be created {instance}: "
                    f"```fix\n"
                    f"{list_roles}```"
                    "These roles are required for the registration to function correctly.\n"
                    "They will be made with no permissions. You can modify this later through Role"
                    " Management if you "
                    "need/want to.\nDo you wish to continue?\n\n`Yes`\n`No`\n **[This command will time out in 60s]**"
                )
                try:
                    set_role = await ctx.bot.wait_for("message", timeout=60.0, check=check)
                except asyncio.TimeoutError:
                    return await ctx.send("Timed out")
                if set_role.content.lower() == "no":
                    await ctx.send(
                        "Okay, I won't touch anything. Do keep in mind this must be done before registration will work!"
                    )
                elif set_role.content.lower() == "yes":
                    created = 0
                    await ctx.send("Okay, this will just take a moment~")
                    for role in roles_to_add:
                        role_check = discord.utils.get(guild.roles, name=role)
                        if not role_check:
                            await guild.create_role(name=role)
                            created += 1
                    await ctx.send(f"All done! Created {created} roles.\n"
                                   f"Attempting to save the role IDs to my registration database...")

                    await add_registration_roles(ctx)
                    await ctx.send("Done!")
                else:
                    await ctx.send(
                        "You have entered an invalid response. Valid responses include `yes` and `no`. Please run the "
                        "command again."
                    )
            except discord.HTTPException or discord.Forbidden:
                await ctx.send(
                    "Creation of roles has failed. The most common problems are that I don't have the `Manage Roles` "
                    "permission on the server. Please check this and try again!"
                )
        elif guild_data['registration_roles_setup']:
            await ctx.send("Please wait while I attempt to automatically fix the issue.")
            regroles = ujson.loads(guild_data['registration_roles'])
            if guild_data['registration_nsfw']:
                for role in nsfw_sfw_roles:
                    for db_role, db_role_id in regroles.items():
                        if role == db_role:
                            guild_role = ctx.guild.get_role(db_role_id)
                            if guild_role is None:
                                role_check = discord.utils.get(guild.roles, name=role)
                                if not role_check:
                                    new_role = await ctx.guild.create_role(name=role)
                                    regroles[role] = new_role.id
                                    await ctx.send(f"Role {role} is missing, Created {new_role.mention}.")
                new_data = ujson.dumps(regroles)
                async with ctx.pool.acquire() as db:
                    await ctx.pool.execute(
                        "UPDATE botsettings_guild SET registration_roles = $2 WHERE id = $1",
                        ctx.guild.id, new_data
                    )

                await ctx.send("done!")

    # Pourquoi est-ce vide?
    @commands.group(name="reg", aliases=['registration'])
    async def reg_conf(self, ctx):
        pass

    @reg_conf.command(name='diagnose')
    async def reg_diagnose(self, ctx):
        """Registration Self Diagnose Test"""
        msg = await ctx.send("Please wait while self diagnostic is running for the registration module...")

        async with ctx.pool.acquire() as db:
            guild_data = await ctx.pool.fetchrow(
                "SELECT registration_channel, registration_channel_lock, "
                "registration_nsfw, registration_intro_enabled, "
                "registration_intro_channel, registration_intro_message, "
                "registration_cleanup_toggle, registration_enabled, registration_output "
                "registration_roles, premium FROM botsettings_guild WHERE id = $1",
                ctx.guild.id
            )
        output_reg = ctx.guild.get_channel(guild_data['registration_output'])
        if guild_data['registration_channel_lock']:
            reg_channel = ctx.guild.get_channel(guild_data['registration_channel'])
        else:
            reg_channel = None
        check_roles = ""
        for db_role, role_id in ujson.loads(guild_data['registration_roles']).items():
            guild_role = ctx.guild.get_role(role_id)
            if guild_role is None:
                check_roles += f"**{db_role}**: Error: Role missing or insufficient permissions.\n"
            else:
                check_roles += f"**{db_role}**: {guild_role.mention}\n"

        output_reg_msg = output_reg.mention if not None else "Channel permissions broken or channel does not exist."
        reg_channel_msg = reg_channel.mention if not None else "Channel permissions broken or channel does not exist."
        embed = discord.Embed(
            color=ctx.color,
            title="Registration Self Diagnostic Test",
            description=f"Output Channel: "
                        f"{output_reg_msg}"
                        f"\nRegistration Lock: {'On' if guild_data['registration_channel_lock'] else 'Off'}\n"
                        f"Registration Channel: "
                        f"{reg_channel_msg}"
                        f"\nRegistration Roles Check:\n"
                        f"{check_roles}"
        )

        if guild_data['premium']:
            embed.add_field(name="Premium Functions",
                            value="Not yet developed")
        await msg.edit(content="Here are the results from the test", embed=embed)

    @commands.command()
    @commands.guild_only()
    @commands.max_concurrency(1, commands.BucketType.user)
    async def register(self, ctx):
        async with ctx.pool.acquire() as db:
            reg_data = await db.fetchrow(
                "SELECT registration_channel, registration_channel_lock, "
                "registration_nsfw, registration_cleanup_toggle,registration_enabled, registration_roles "
                "FROM botsettings_guild WHERE id = $1",
                ctx.guild.id
            )
        ################################################################################################
        #                           Registration Fail Safe Checks
        ################################################################################################
        # Check to see if registration is actually set up in the first place
        if not reg_data['registration_enabled']:
            return await ctx.send(
                "Registration has not been setup in this server."
                " Please consult your server admin/owner for your server."
            )
        # Registration is set up, but does role ID data exist?
        if not reg_data['registration_roles']:
            return await ctx.send(
                "Looks like this server's registration data isn't properly saved to my registration "
                "database. Please run the `furregroles` command to fix this."
            )

        # Load the roles from the database
        registration_roles = await load_registration_roles(ctx)
        if not registration_roles:
            return await ctx.send(
                "It looks like this server's registration role ID data is missing from my database! "
                "You can fix this by running my `furregroles` command. Registration should start working "
                "again once everything is in check!"
            )

        # Check the output channel
        output_channel = await registration_output(ctx)
        if output_channel is None:
            await ctx.send(
                "No registration output channel has been set. You can fix this in your server settings on my "
                "dashboard at <https://sheri.bot/settings>. "
                "Select your server > Registration > Select a channel from the `Registration Channel` dropdown menu.")
            return
        # Check to see if the caller has already registered
        if registration_roles['Registered'] in ctx.author.roles:
            await send_message(ctx, message="You have already registered to this server."
                                            " You can unregister by using the command ``furunregister``")
            return

        # Check to see if the registration channel is enabled and channel is valid
        if reg_data['registration_channel_lock']:
            # check the channel to see if its usable
            reg_channel = ctx.guild.get_channel(reg_data['registration_channel'])
            if reg_channel is not None and ctx.channel is not reg_channel:
                return await ctx.send(f"You can't register in this channel. Please go to "
                                      f"{reg_channel.mention} to register.")

        #################################################################################################
        #                       Registration Global Variables
        #################################################################################################
        information, sexual_questions, give_roles, nsfw = "", None, [], reg_data['registration_nsfw']
        errors = {
            "Permission Error": f"{ctx.author}, I have attempted to do something "
                                f"that requires a server permission I don't have, "
                                f"or I couldn't manage the role that I need to add to you.",
            "Timed Out": f"Sorry, {ctx.author.name}. Registration has timed out."
                         f" You will need to run `furregister` again."
        }

        ################################################################################################
        #                     Registration Global Check
        #################################################################################################
        def check(m):
            return isinstance(m.channel, discord.DMChannel) and m.author == ctx.author

        #################################################################################################
        #                       Registration Notification DM LOGIC
        #################################################################################################
        try:
            if reg_data['registration_cleanup_toggle']:
                await ctx.send(
                    f"Please make sure your direct messages are open **{ctx.author.name}** as I will "
                    f"direct message you to collect your info.\n"
                    f"Do **NOT** lie, as this can get you __banned__ or __penalized__.", delete_after=15)
                if can_delete(ctx):
                    await ctx.message.delete()

            else:
                await ctx.send(f"Please make sure your direct messages are open **{ctx.author.name}** as I will "
                               f"direct message you to collect your info.\n"
                               f"Do **NOT** lie, as this can get you __banned__ or __penalized__.")
        except (discord.Forbidden, discord.NotFound):
            pass
        ####################################################################################################
        #                           Registration Forum Logic
        ####################################################################################################

        # Gender Question Logic
        try:
            await ctx.author.send(
                "__**What gender do you identify as?**__\n"
                "Type just the Number from the choices below:"
                "```fix\n"
                "1 - Male | 2 - Female | 3 - Genderfluid | 4 - Agender | "
                "5 - Non-Binary | 6 - Transgender | 7 - Transgender Male | "
                "8 - Transgender Female,"
                "```"
            )
        except discord.Forbidden:
            return await ctx.send(
                f"It appears that I cannot DM you due to your privacy settings, {ctx.author.mention}!\n"
                "Please update your privacy settings. You can revert "
                "your settings once registration is complete."
            )

        try:
            while True:

                try:
                    response = await ctx.bot.wait_for("message", timeout=60, check=check)
                except asyncio.TimeoutError:
                    return await ctx.author.send(
                        errors['Timed Out']
                    )
                response = response.content
                options = [
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "6",
                    "7",
                    "8",
                ]
                if response not in options:
                    await ctx.author.send(
                        "Invalid response.\n"
                        "\n"
                        "__**What gender do you identify as?**__"
                        "Type just the Number from the choices below:"
                        "```fix\n"
                        "1 - Male | 2 - Female | 3 - Genderfluid | "
                        "4 - Agender | 5 - Non-Binary | 6 - Transgender | "
                        "7 - Transgender Male | 8 - Transgender Female,"
                        "```"
                    )
                else:
                    if response == "1":
                        give_roles.append(registration_roles['Male'])
                        information += "Gender: ``Male``\n"

                    elif response == "2":
                        give_roles.append(registration_roles['Female'])
                        information += "Gender: ``Female``\n"

                    elif response == "3":
                        give_roles.append(registration_roles['Genderfluid'])
                        information += "Gender: ``Genderfluid``\n"

                    elif response == "4":
                        give_roles.append(registration_roles['Agender'])
                        information += "Gender: ``Agender``\n"

                    elif response == "5":
                        give_roles.append(registration_roles['Non-binary'])
                        information += "Gender: ``Non-Binary``\n"

                    elif response == "6":
                        give_roles.append(registration_roles['Transgender'])
                        information += "Gender: ``Transgender``\n"

                    elif response == "7":
                        ge_roles = ["Male", "Transgender"]
                        for x in ge_roles:
                            give_roles.append(registration_roles[x])
                        information += "Gender: ``Transgender Male``\n"

                    elif response == "8":
                        ge_roles = ["Female", "Transgender"]
                        for x in ge_roles:
                            give_roles.append(registration_roles[x])
                        information += "Gender: ``Transgender Female``\n"

                    break
                if not response:
                    break

            # Rules Question Logic
            await ctx.author.send(
                content=f"**__Have you read the rules of ``{ctx.guild.name}`` and will you comply with them?__**\n"
                        "The following responses are valid for this question:\n"
                        "```fix\n"
                        "Yes | No```")

            while True:
                try:
                    response = await ctx.bot.wait_for("message", timeout=60, check=check)
                except asyncio.TimeoutError:
                    return await ctx.author.send(errors['Timed Out'])

                options = ["yes", "no"]

                if response.content.lower() not in options:
                    await ctx.author.send("Invalid response."
                                          "\n"
                                          f"**__Have you read the rules of `{ctx.guild.name}` "
                                          f"and will you comply with them?__**\n"
                                          "The following responses are valid for this question:\n"
                                          "```fix\n"
                                          "Yes | No```")
                else:
                    if response.content.lower() == "yes":
                        pass
                    elif response.content.lower() == "no":
                        return await ctx.author.send(
                            f"You'd better go and read the rules of `{ctx.guild}` and re-run registration."
                        )
                    break
                if not response:
                    break

            # Mention Question Logic
            await ctx.author.send(
                "__**Are you okay with being mentioned?**__\n"
                "The following responses are valid for this question:\n"
                "```fix\n"
                "Yes | No```"
            )

            while True:
                options = ["yes", "no"]
                try:
                    response = await ctx.bot.wait_for("message", timeout=60, check=check)
                except asyncio.TimeoutError:
                    return await ctx.author.send(
                        errors['Timed Out'])
                if response.content.lower() not in options:
                    await ctx.author.send("Invalid response."
                                          "\n"
                                          "__**Are you okay with being mentioned?**__\n"
                                          "The following responses are valid for this question:\n"
                                          "```fix\n"
                                          "Yes | No```")
                else:
                    if response.content.lower() == "yes":
                        give_roles.append(registration_roles['Mention'])
                        information += "Mentions: ``Yes``\n"
                    elif response.content.lower() == "no":
                        give_roles.append(registration_roles['No Mention'])
                        information += "Mentions: ``No``\n"
                    break
                if not response:
                    break

            # Age Question
            await ctx.author.send(
                "__**What is your date of birth?**__\n"
                "The current valid date format is ``YYYY/MM/DD``\n"
                "An example of the date format is: ``1900/11/01``\n"
                "Do **NOT** Lie about your age; it can get you into"
                " some **SERIOUS** trouble."
            )
            while True:
                try:
                    response = await ctx.bot.wait_for("message", timeout=30, check=check)
                except asyncio.TimeoutError:
                    return await ctx.author.send(errors['Timed Out'])
                birthdate_response = re.match(
                    "((?:19|20)\d\d)/(?:0[1-9]|1[012])/(?:0[1-9]|[12]\d|3[01])",
                    response.content
                )
                if not birthdate_response:
                    await ctx.author.send(
                        "You need to use the proper format. ``YYYY/MM/DD``. Please try again."
                    )
                else:
                    birthdate_datetime = datetime.strptime(birthdate_response.group(0), "%Y/%m/%d")
                    delta = relativedelta(datetime.now(), birthdate_datetime)
                    if int(delta.years) >= 69:
                        return await ctx.author.send("HA, you're funny! And I'm 1,000 years old!")
                    elif int(delta.years) >= 18:
                        give_roles.append(registration_roles['18+'])
                        information += f"Age: ``{delta.years}`` Years\n"
                    elif int(delta.years) < 13:
                        return await ctx.author.send("Registration Ended")
                    elif int(delta.years) <= 17:
                        give_roles.append(registration_roles['Underage'])
                        information += f"Age: ``{delta.years}`` Years\n"
                    break
                if not response:
                    break  # me daddy

            # Check to see if the user is applicable for above 18+ questions which are allowed by discord.
            if registration_roles['18+'] in give_roles:

                # RelationShip Status
                await ctx.author.send(
                    "Are you currently ``Taken``, ``Single, Seeking for a partner`` "
                    "or ``Single, Not seeking for a partner`` "
                    "or just ``Single``?\n\n"
                    "Type just the Number from the choices below:\n"
                    "```fix\n"
                    "1 - Taken | 2 - Single | 3 - Single, seeking for partner | "
                    "4 - Single, not seeking for partner```"
                )
                while True:
                    options = [
                        "1",
                        "2",
                        "3",
                        "4"
                    ]

                    try:
                        response = await ctx.bot.wait_for("message", timeout=60, check=check)
                    except asyncio.TimeoutError:
                        return await ctx.author.send(errors['Timed Out'])

                    response = response.content

                    if response not in options:
                        await ctx.author.send(
                            "Invalid response."
                            "\n"
                            "Are you currently ``Taken``, "
                            "``Single, Seeking for a partner`` or ``Single, Not seeking for a partner`` "
                            "or just ``Single``?\n\n"
                            "Type just the Number from the choices below:\n"
                            "```fix\n"
                            "1 - Taken | 2 - Single | 3 - Single, seeking for partner | "
                            "4 - Single, not seeking for partner```"
                        )
                    else:
                        if response == "1":
                            give_roles.append(registration_roles['Taken'])
                            information += "Relationship: ``Taken``\n"
                        elif response == "2":
                            give_roles.append(registration_roles['Single'])
                            information += "Relationship: ``Single``\n"
                        elif response == "3":
                            relationship_roles = ["Seeking for partner", "Single"]
                            for role in relationship_roles:
                                give_roles.append(registration_roles[role])
                            information += "Relationship: ``Single and ready to mingle``\n"
                        elif response == "4":
                            relationship_roles = ['Single', "Not seeking for partner"]
                            for role in relationship_roles:
                                give_roles.append(registration_roles[role])
                            information += "Relationship: ``Single and not ready to mingle``\n"
                        break
                    if not response:
                        break
                if reg_data['registration_nsfw']:

                    # Sexual Content Question
                    await ctx.author.send(
                        f"**__Do you want to view explict content in ``{ctx.guild.name}``?__**\n"
                        "The valid responses for this question are:\n"
                        "```fix\n"
                        "Yes | No```"
                    )
                    while True:
                        options = ["yes", "no"]
                        try:
                            response = await ctx.bot.wait_for("message", timeout=60, check=check)
                        except asyncio.TimeoutError:
                            return await ctx.author.send(errors['Timed Out'])
                        if response.content.lower() not in options:
                            await ctx.author.send(
                                "Invalid response.\n"
                                f"**__Do you want to view explict content in ``{ctx.guild.name}``?__**\n"
                                "The valid responses for this question are:\n"
                                "```fix\n"
                                "Yes | No```"
                            )
                        else:
                            if response.content.lower() == "yes":
                                give_roles.append(registration_roles['NSFW'])
                            elif response.content.lower() == "no":
                                pass
                            break
                        if not response:
                            break
                    # Sexual Question Answers

                    # Sexual Preference Question
                    await ctx.author.send(
                        "**__Would you like to answer some questions concerning"
                        " your sexuality and preference of sexual position?__**\n"
                        "The valid responses for this question are:\n"
                        "```fix\n"
                        "Yes | No```"
                    )
                    while True:
                        options = ["yes", "no"]
                        try:
                            response = await ctx.bot.wait_for(
                                "message", timeout=60, check=check
                            )
                        except asyncio.TimeoutError:
                            return await ctx.author.send(
                                errors['Timed Out']
                            )
                        if response.content.lower() not in options:
                            await ctx.author.send(
                                "Invalid response."
                                "\n"
                                "**__Would you like to answer some questions concerning"
                                " your sexuality and preference of sexual position?__**\n"
                                "The valid responses for this question are:\n"
                                "```fix\n"
                                "Yes | No```"
                            )
                        else:
                            if response.content.lower() == "yes":
                                sexual_questions = True
                            elif response.content.lower() == "no":
                                sexual_questions = False
                            break
                        if not response:
                            break

                    if sexual_questions:

                        # Sexual Orientation Question
                        await ctx.author.send(
                            "**__What is your sexual orientation.__**\n"
                            "Type just the Number from the choices below:\n"
                            "```fix\n"
                            "1 - Asexual | 2 - Bisexual | 3 - Gay | "
                            "4 - Lesbian | 5 - Pansexual | 6 - Straight | 7 - Aromantic```"
                        )
                        while True:
                            options = [
                                "1",
                                "2",
                                "3",
                                "4",
                                "5",
                                "6",
                                "7",
                            ]
                            try:
                                response = await ctx.bot.wait_for(
                                    "message",
                                    timeout=60,
                                    check=check,
                                )
                            except asyncio.TimeoutError:
                                return await ctx.author.send(
                                    errors['Timed Out']
                                )

                            response = response.content
                            if response not in options:
                                await ctx.author.send(
                                    "Invalid response."
                                    "\n"
                                    "**__What is your sexual orientation.__**\n"
                                    "Type just the Number from the choices below:\n"
                                    "```fix\n"
                                    "1 - Asexual | 2 - Bisexual | 3 - Gay | "
                                    "4 - Lesbian | 5 - Pansexual | 6 - Straight | 7 - Aromantic```"
                                )
                            else:
                                if response == "1":
                                    give_roles.append(registration_roles['Asexual'])
                                    information += "Sexual Orientation: ``Asexual``\n"
                                elif response == "2":
                                    give_roles.append(registration_roles['Bisexual'])
                                    information += "Sexual Orientation: ``Bisexual``\n"
                                elif response == "3":
                                    give_roles.append(registration_roles['Gay'])
                                    information += "Sexual Orientation: ``Gay``\n"
                                elif response == "4":
                                    give_roles.append(registration_roles['Lesbian'])
                                    information += "Sexual Orientation: ``Lesbian``\n"
                                elif response == "5":
                                    give_roles.append(registration_roles['Pansexual'])
                                    information += "Sexual Orientation: ``Pansexual``\n"
                                elif response == "6":
                                    give_roles.append(registration_roles['Straight'])
                                    information += "Sexual Orientation: ``Straight``\n"
                                elif response == "7":
                                    give_roles.append(registration_roles['Aromantic'])
                                    information += "Sexual Orientation: ``Aromantic``\n"
                                break
                            if not response:
                                break

                        # Sexual Position Question
                        await ctx.author.send(
                            "__**What sexual position do you prefer?**__\n\n"
                            "Type just the Number from the choices below:\n"
                            "```fix\n"
                            "1 - Dominant | 2 - Submissive | 3 - Switch | "
                            "4 - Rather Not say | 5 - Neither```"
                        )
                        while True:
                            options = [
                                "1",
                                "2",
                                "3",
                                "4",
                                "5",
                            ]
                            try:
                                response = await ctx.bot.wait_for(
                                    "message",
                                    timeout=60,
                                    check=check,
                                )
                            except asyncio.TimeoutError:
                                return await ctx.author.send(
                                    "Registration has timed out."
                                )
                            if response.content.lower() not in options:
                                await ctx.author.send(
                                    "Invalid response."
                                    "\n"
                                    "__**What sexual position do you prefer?**__\n\n"
                                    "Type just the Number from the choices below:\n"
                                    "```fix\n"
                                    "1 - Dominant | 2 - Submissive | 3 - Switch | "
                                    "4 - Rather Not say | 5 - Neither```"
                                )
                            else:
                                if response.content.lower() == "1":
                                    give_roles.append(registration_roles['Dominant'])
                                    information += "Sexual Position: ``Dominant``\n"
                                elif response.content.lower() == "2":

                                    give_roles.append(registration_roles['Submissive'])
                                    information += "Sexual Position: ``Submissive``\n"
                                elif response.content.lower() == "3":

                                    give_roles.append(registration_roles['Switch'])
                                    information += "Sexual Position: ``Switch``\n"
                                elif response.content.lower() == "4":
                                    information += "Sexual Position: ``Rather not say``\n"
                                elif response.content.lower() == "5":
                                    information += "Sexual Position: ``Neither``\n"
                                break
                            if not response:
                                break

            # INTRODUCTION LOGIC AND FINISHING LOGIC
            registration_embed = discord.Embed(color=ctx.color,
                                               description=information)
            registration_embed.set_author(name=f"{ctx.author}'s Registration")
            registration_embed.set_footer(
                text=f"UID: {ctx.author.id}",
                icon_url="https://cdn.discordapp.com/emojis/457367016823848970.png?v=1"
            )
            registration_embed.set_thumbnail(url=avatar_check(ctx.author))
            await ctx.author.send(
                "**__Would you like to introduce yourself?__**\n"
                "```fix\n"
                "YES | NO```"
            )
            while True:
                options = [
                    "yes",
                    "no"
                ]
                try:
                    response = await ctx.bot.wait_for(
                        "message",
                        timeout=60,
                        check=check,
                    )
                except asyncio.TimeoutError:
                    return await ctx.author.send(
                        errors['Timed Out']
                    )
                if response.content.lower() not in options:
                    await ctx.author.send(
                        "Invalid response."
                        "\n"
                        "**__Would you like to introduce yourself?__**\n"
                        "```fix\n"
                        "YES | NO```"
                    )
                else:
                    if response.content.lower() == "yes":
                        await ctx.author.send(
                            content="Please introduce yourself to me in this direct message.\n"
                                    "After you have introduced yourself, your registration will be completed.\n"
                                    "If at any time you need to change/adjust/update your registration, "
                                    "You can furunregister and re-register again.")
                        try:
                            response = await ctx.bot.wait_for("message", timeout=1600, check=check)
                        except asyncio.TimeoutError:
                            registration_embed.add_field(
                                name="About:", value="A mysterious person..."
                            )
                        else:
                            page_num = 0
                            pages = pagify(response.content, None, 0, 1000)
                            for page in pages:
                                page_num += 1
                                registration_embed.add_field(
                                    name=f"About{' (continued):' if page_num > 1 else ':'}",
                                    value=page,
                                    inline=False,
                                )
                    give_roles.append(registration_roles['Registered'])
                    await ctx.author.send(
                        "Thank you, Your registration is now completed. You may now browse the server.")
                    if can_embed(guild=ctx.guild, channel=output_channel):
                        registration_embed.set_thumbnail(url=avatar_check(ctx.author))
                        await output_channel.send(
                            embed=registration_embed)
                    await ctx.author.add_roles(*give_roles, reason="Registration")
                    break
                if not response:
                    break
        except (discord.Forbidden, discord.NotFound):
            return

    @commands.guild_only()
    @commands.command()
    async def unregister(self, ctx):
        """Remove your roles from registration, allowing you to register again"""
        if not can_manage_user(ctx, ctx.author):
            return await ctx.send(
                "I don't have a role above you which means I can't manage your roles,"
                " please have someone with permissions move my role up!"
            )
        remove = []
        msg = await ctx.send(content=f"{Get_emote.get_emote(paw=True)} Processing...")
        for role in roles:
            check = discord.utils.get(ctx.guild.roles, name=role)
            if check in ctx.author.roles:
                remove.append(check)
        await ctx.author.remove_roles(*remove, reason="User ran unregister command")
        await msg.edit(f"Done, you may now register again **{ctx.author}** with the command ``furregister``.")


def setup(bot):
    bot.add_cog(Registration(bot))
